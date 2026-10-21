#include "voice_session.h"
#include "board_config.h"
#include "audio_output.h"
#include "music_player.h"
#include "music_eq.h"
#include "emergency_alert.h"
#include "codec2.h"
#include "voice_decoder.h"
#include "esp_log.h"
#include "esp_heap_caps.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include <string.h>

static const char *TAG = "VOICE_SESSION";
/* decode_2400 -> aks_to_M2 -> lpc_post_filter alone needs 15,344 bytes
 * with the ESP32 compiler; leave room for FFT, worker and runtime calls. */
#define VOICE_TASK_STACK_BYTES (32 * 1024)
static portMUX_TYPE s_lock = portMUX_INITIALIZER_UNLOCKED;
static bool s_active, s_output_busy;
static voice_output_state_t s_output_state = VOICE_OUTPUT_IDLE;
static audio_direction_t s_direction = AUDIO_DIR_FIELD_TX;
static uint32_t s_generation, s_session, s_ptt_request;
static uint32_t session_id(const uint8_t *p) {
    return ((uint32_t)p[0]<<24)|((uint32_t)p[1]<<16)|((uint32_t)p[2]<<8)|p[3];
}
static QueueHandle_t s_packets;
static TaskHandle_t s_task;

typedef struct {
    uint32_t generation;
    uint16_t sequence;
    uint8_t frames;
    uint8_t data[CODEC2_MAX_FRAMES_PER_PACKET * CODEC2_2400_BYTES_PER_FRAME];
} voice_packet_t;

static bool control_active(uint32_t generation)
{
    portENTER_CRITICAL(&s_lock);
    bool active = s_active && s_direction == AUDIO_DIR_CONTROL_TX
                  && generation == s_generation;
    portEXIT_CRITICAL(&s_lock);
    return active;
}

static void output_busy(bool busy)
{
    portENTER_CRITICAL(&s_lock);
    s_output_busy = busy;
    if (!busy && s_output_state == VOICE_OUTPUT_STOPPING)
        s_output_state = VOICE_OUTPUT_IDLE;
    portEXIT_CRITICAL(&s_lock);
}

/* Publish only for the generation that actually acquired/released the device. */
static void output_state(uint32_t generation, voice_output_state_t state)
{
    portENTER_CRITICAL(&s_lock);
    if (generation == s_generation) s_output_state = state;
    portEXIT_CRITICAL(&s_lock);
}

voice_output_state_t voice_session_output_state(void)
{
    portENTER_CRITICAL(&s_lock);
    voice_output_state_t state = s_output_state;
    portEXIT_CRITICAL(&s_lock);
    return state;
}

/* 8kHz Codec2 -> 16kHz I2S: hold each sample twice, duplicate L/R.
 * 160 input samples become 320 stereo frames, still exactly 20ms. */
static bool write_frame(const int16_t *mono, uint32_t generation)
{
    if (!control_active(generation)) return false;
    int16_t stereo[640];
    for (unsigned i = 0; i < 160; ++i) {
        int16_t sample = mono ? mono[i] : 0;
        for (unsigned j = 0; j < 4; ++j) stereo[4*i+j] = sample;
    }
    bool ok = audio_output_write(stereo, 640);
    if (!ok) vTaskDelay(pdMS_TO_TICKS(20));
    return ok;
}

static void playback_task(void *arg)
{
    (void)arg;
    struct CODEC2 *decoder = NULL;
    uint32_t generation = 0;
    bool have_sequence = false;
    uint16_t previous = 0;
    unsigned packets = 0, missing = 0, underflows = 0;
    uint32_t restore_rate = 0;
    bool init_failed = false;
    uint32_t failed_generation = 0;
    voice_packet_t packet;
    while (1) {
        if (decoder && !control_active(generation)) {
            voice_decoder_destroy(decoder);
            decoder = NULL;
            /* Release decoder memory before recreating the normal DMA profile. */
            if (restore_rate) audio_output_init(restore_rate);
            else audio_output_deinit();
            audio_output_release();
            output_busy(false);
        }
        portENTER_CRITICAL(&s_lock);
        uint32_t desired_generation = s_generation;
        bool prepare = s_active && s_direction == AUDIO_DIR_CONTROL_TX;
        portEXIT_CRITICAL(&s_lock);
        /* PTT prepares output before the sender is allowed to send audio. */
        if (!decoder && prepare && !(init_failed && desired_generation == failed_generation)) {
            generation = desired_generation;
            output_busy(true);
            if (!audio_output_claim()) {
                output_busy(false);
                init_failed = true;
                failed_generation = generation;
                output_state(generation, VOICE_OUTPUT_FAILED);
                continue;
            }
            restore_rate = music_player_is_playing() ? audio_output_get_sample_rate() : 0;
            bool stopped = emergency_alert_stop() && music_player_pause();
            for (unsigned i = 0; i < 100 && music_player_is_playing() && !music_player_is_paused()
                    && control_active(generation); ++i)
                vTaskDelay(pdMS_TO_TICKS(10));
            if (!stopped || (music_player_is_playing() && !music_player_is_paused()) || emergency_alert_is_active()
                    || !control_active(generation)) {
                ESP_LOGW(TAG, "Voice output unavailable: previous audio did not stop");
                init_failed = true;
                failed_generation = generation;
                output_state(generation, VOICE_OUTPUT_FAILED);
                audio_output_release();
                output_busy(false);
                continue;
            }
            ESP_LOGI(TAG, "Decoder heap before free=%u largest=%u",
                     (unsigned)heap_caps_get_free_size(MALLOC_CAP_8BIT),
                     (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_8BIT));
            /* Free music DMA and reserve the small DMA profile before general
             * decoder allocations consume the remaining DMA-capable heap. */
            bool output_ready = audio_output_init_voice();
            decoder = output_ready ? voice_decoder_create() : NULL;
            if (!output_ready) ESP_LOGE(TAG, "Voice I2S DMA initialization failed");
            else if (!decoder) ESP_LOGE(TAG, "Codec2 decoder allocation failed");
            else if (codec2_samples_per_frame(decoder) != 160 || codec2_bits_per_frame(decoder) != 48)
                ESP_LOGE(TAG, "Codec2 decoder format mismatch samples=%d bits=%d",
                    codec2_samples_per_frame(decoder), codec2_bits_per_frame(decoder));
            if (!decoder || codec2_samples_per_frame(decoder) != 160
                    || codec2_bits_per_frame(decoder) != 48) {
                if (decoder) voice_decoder_destroy(decoder);
                decoder = NULL;
                audio_output_deinit();
                if (restore_rate) audio_output_init(restore_rate);
                init_failed = true;
                failed_generation = generation;
                output_state(generation, VOICE_OUTPUT_FAILED);
                audio_output_release();
                output_busy(false);
                ESP_LOGE(TAG, "Codec2/I2S initialization failed; retry with PTT off/on heap_free=%u largest=%u",
                         (unsigned)heap_caps_get_free_size(MALLOC_CAP_8BIT),
                         (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_8BIT));
                continue;
            }
            init_failed = false;
            have_sequence = false;
            packets = missing = underflows = 0;
            output_state(generation, VOICE_OUTPUT_READY);
            ESP_LOGI(TAG, "Codec2 playback decode=8000Hz output=16000Hz stereo I2S ready");
        }
        if (xQueueReceive(s_packets, &packet,
                          decoder && have_sequence ? 0 : pdMS_TO_TICKS(20)) != pdTRUE) {
            /* Waiting for first audio is normal, not a playback underflow. */
            if (decoder && have_sequence) {
                ++underflows;
                write_frame(NULL, generation);
                if (underflows == 1 || underflows % 50 == 0)
                    ESP_LOGW(TAG, "Voice buffer empty blocks=%u", underflows);
            }
            continue;
        }
        if (!decoder || packet.generation != generation || !control_active(generation)) continue;
        if (!have_sequence) {
            /* Start the jitter-buffer deadline at the first packet, not PTT. */
            for (unsigned i = 0; i < 60 && uxQueueMessagesWaiting(s_packets) < 2
                    && control_active(generation); ++i)
                vTaskDelay(pdMS_TO_TICKS(10));
            if (!control_active(generation)) continue;
        }
        uint16_t delta = (uint16_t)(packet.sequence - previous);
        if (have_sequence && (delta == 0 || delta >= 0x8000)) continue;
        if (have_sequence && delta > 1) {
            missing += delta - 1;
            ESP_LOGW(TAG, "Voice missing=%u total=%u", delta-1, missing);
            /* Bounded silence; missing audio cannot be reconstructed. */
            unsigned silent = delta <= 4 ? (delta-1) * packet.frames : 0;
            for (unsigned i = 0; i < silent && control_active(generation); ++i)
                write_frame(NULL, generation);
        }
        previous = packet.sequence;
        have_sequence = true;
        int16_t mono[160];
        unsigned pcm_peak = 0;
        for (unsigned i = 0; i < packet.frames && control_active(generation); ++i) {
            codec2_decode(decoder, mono, packet.data + i * 6);
            for (unsigned j = 0; j < 160; ++j) {
                int32_t sample = mono[j];
                unsigned magnitude = (unsigned)(sample < 0 ? -sample : sample);
                if (magnitude > pcm_peak) pcm_peak = magnitude;
            }
            if (!write_frame(mono, generation)) {
                ESP_LOGW(TAG, "Voice I2S write failed/interrupted");
                break;
            }
        }
        ++packets;
        if (packets == 1 || packets % 25 == 0)
            ESP_LOGI(TAG, "Codec2 PLAY seq=%u packets=%u missing=%u empty=%u queued=%u pcm_peak=%u stack_free_bytes=%u",
                     packet.sequence, packets, missing, underflows,
                     (unsigned)uxQueueMessagesWaiting(s_packets), pcm_peak,
                     (unsigned)uxTaskGetStackHighWaterMark(NULL));
    }
}

void voice_session_init(void)
{
    s_packets = xQueueCreate(12, sizeof(voice_packet_t));
    if (!s_packets || xTaskCreate(playback_task, "codec2_play", VOICE_TASK_STACK_BYTES, NULL, 5, &s_task) != pdPASS)
        ESP_LOGE(TAG, "Voice playback task allocation failed stack=%u", (unsigned)VOICE_TASK_STACK_BYTES);
    else
        ESP_LOGI(TAG, "Voice playback task ready stack=%u", (unsigned)VOICE_TASK_STACK_BYTES);
}

static void change_session(bool active, audio_direction_t direction)
{
    portENTER_CRITICAL(&s_lock);
    bool changed = s_active != active || s_direction != direction;
    s_active = active;
    s_direction = direction;
    if (changed) {
        ++s_generation;
        s_output_state = active && direction == AUDIO_DIR_CONTROL_TX
            ? VOICE_OUTPUT_PREPARING
            : (s_output_busy ? VOICE_OUTPUT_STOPPING : VOICE_OUTPUT_IDLE);
    }
    portEXIT_CRITICAL(&s_lock);
    if (changed && s_packets) xQueueReset(s_packets);
    if (direction != AUDIO_DIR_CONTROL_TX || !active) {
        /* Let worker release I2S before the controller accepts new music. */
        for (unsigned i = 0; i < 100; ++i) {
            portENTER_CRITICAL(&s_lock);
            bool busy = s_output_busy;
            portEXIT_CRITICAL(&s_lock);
            if (!busy) break;
            vTaskDelay(pdMS_TO_TICKS(10));
        }
    }
}

void voice_session_start(void) {
    change_session(true, AUDIO_DIR_FIELD_TX);
    music_eq_suspend();
    ESP_LOGI(TAG, "CALL START -> FIELD_TX");
}
void voice_session_stop(void) {
    change_session(false, AUDIO_DIR_FIELD_TX);
    music_eq_resume();
    ESP_LOGI(TAG, "CALL STOP");
}
bool voice_session_set_direction(audio_direction_t direction)
{
    if (direction != AUDIO_DIR_FIELD_TX && direction != AUDIO_DIR_CONTROL_TX) return false;
    if (direction == AUDIO_DIR_CONTROL_TX && (!s_task || !s_packets)) return false;
    portENTER_CRITICAL(&s_lock);
    bool active = s_active;
    portEXIT_CRITICAL(&s_lock);
    if (!active) return false;
    change_session(active, direction);
    ESP_LOGI(TAG, "DIRECTION -> %s", direction == AUDIO_DIR_CONTROL_TX ? "CONTROL_TX" : "FIELD_TX");
    return true;
}
bool voice_session_sync_direction(audio_direction_t direction)
{
    if (direction != AUDIO_DIR_FIELD_TX && direction != AUDIO_DIR_CONTROL_TX) return false;
    if (direction == AUDIO_DIR_CONTROL_TX && (!s_task || !s_packets)) {
        ESP_LOGW(TAG, "Reject P4 direction: playback task/queue unavailable");
        return false;
    }
    portENTER_CRITICAL(&s_lock);
    bool active = s_active;
    portEXIT_CRITICAL(&s_lock);
    if (!active) {
        ESP_LOGW(TAG, "Restore call from P4 direction command after missing START/reboot");
        voice_session_start();
    }
    return voice_session_set_direction(direction);
}
bool voice_session_is_active(void)
{
    portENTER_CRITICAL(&s_lock);
    bool active = s_active || s_output_busy;
    portEXIT_CRITICAL(&s_lock);
    return active;
}
audio_direction_t voice_session_get_direction(void)
{
    portENTER_CRITICAL(&s_lock);
    audio_direction_t direction = s_direction;
    portEXIT_CRITICAL(&s_lock);
    return direction;
}
bool voice_session_handle_codec2(const uint8_t *payload, size_t length)
{
    if (!payload || length < AUDIO_CODEC2_META_SIZE || payload[0] != AUDIO_DATA_CODEC2
        || payload[1] != CODEC2_MODE_2400 || payload[2] != AUDIO_DIR_CONTROL_TX
        || payload[5] == 0 || payload[5] > CODEC2_MAX_FRAMES_PER_PACKET
        || payload[6] != CODEC2_2400_BYTES_PER_FRAME
        || length != AUDIO_CODEC2_META_SIZE + (size_t)payload[5] * 6) {
        if (payload && length >= AUDIO_CODEC2_META_SIZE)
            ESP_LOGW(TAG, "Reject Codec2 metadata type=%u mode=%u direction=%u frames=%u bpf=%u len=%u",
                     payload[0], payload[1], payload[2], payload[5], payload[6], (unsigned)length);
        else
            ESP_LOGW(TAG, "Reject Codec2 short/null payload len=%u", (unsigned)length);
        return false;
    }
    if (!s_packets || !s_task) {
        ESP_LOGW(TAG, "Reject Codec2: playback task/queue unavailable");
        return false;
    }
    portENTER_CRITICAL(&s_lock);
    voice_packet_t packet = {.generation=s_generation,
        .sequence=((uint16_t)payload[3] << 8) | payload[4], .frames=payload[5]};
    bool session_active = s_active;
    audio_direction_t session_direction = s_direction;
    bool active = session_active && session_direction == AUDIO_DIR_CONTROL_TX
        && s_session && session_id(payload+7)==s_session;
    portEXIT_CRITICAL(&s_lock);
    if (!active) {
        ESP_LOGW(TAG, "Reject Codec2 session active=%d session_dir=%u packet_dir=%u seq=%u",
                 session_active, (unsigned)session_direction, payload[2], packet.sequence);
        return false;
    }
    memcpy(packet.data, payload + AUDIO_CODEC2_META_SIZE, packet.frames * 6);
    if (xQueueSend(s_packets, &packet, 0) != pdTRUE) {
        ESP_LOGW(TAG, "Voice queue full; packet dropped seq=%u", packet.sequence);
        return false;
    }
    return true;
}

/* P4 owns call state; repeated START for the same active session is a no-op. */
bool voice_session_control(const protocol_frame_t *f) {
    if (f->src != NODE_P4 || f->railing_id != RAILING_ID) return false;
    unsigned offset=f->cmd==CMD_SET?1:0;
    if (f->payload_len != (f->cmd==CMD_SET?9:4)) return false;
    uint32_t id=session_id(f->payload+offset);
    if (!id && f->cmd!=CMD_STOP) return false;
    portENTER_CRITICAL(&s_lock);
    bool same=id==s_session, active=s_active;
    if(f->cmd==CMD_START && !same) {s_session=id; s_ptt_request=0; ++s_generation;}
    portEXIT_CRITICAL(&s_lock);
    if(f->cmd==CMD_START) {
        if(same)return active; /* reject an ended session's duplicate START */
        voice_session_start();return true;
    }
    if(f->cmd==CMD_STOP && !active)return true;
    if(!same)return false;
    if(!active)return false;
    if(f->cmd==CMD_STOP){voice_session_stop();return true;}
    if(f->cmd==CMD_SET) {
        uint32_t request=session_id(f->payload+5);
        if(request<s_ptt_request)return false;
        if(request==s_ptt_request)return f->payload[0]==voice_session_get_direction();
        if(!voice_session_set_direction((audio_direction_t)f->payload[0]))return false;
        s_ptt_request=request;return true;
    }
    return false;
}
bool voice_session_forward_allowed(const protocol_frame_t *f) {
    if(f->service!=SERVICE_AUDIO || f->cmd!=CMD_DATA || !f->payload_len ||
       f->payload[0]!=AUDIO_DATA_CODEC2)return true;
    if(f->railing_id!=RAILING_ID || f->src!=NODE_S3 || f->dst!=NODE_PI || f->payload_len<AUDIO_CODEC2_META_SIZE ||
       f->payload[1]!=CODEC2_MODE_2400 || f->payload[2]!=AUDIO_DIR_FIELD_TX ||
       !f->payload[5] || f->payload[5]>CODEC2_MAX_FRAMES_PER_PACKET ||
       f->payload[6]!=6 || f->payload_len!=AUDIO_CODEC2_META_SIZE+f->payload[5]*6)return false;
    portENTER_CRITICAL(&s_lock);
    bool allowed=s_active && s_direction==AUDIO_DIR_FIELD_TX && s_session &&
        session_id(f->payload+7)==s_session;
    portEXIT_CRITICAL(&s_lock);
    return allowed;
}

bool voice_session_readiness(const protocol_frame_t *f, protocol_frame_t *reply) {
    if(f->cmd==CMD_CALL_HEALTH) {
        if(f->src!=NODE_P4 || f->dst!=NODE_WROOM || f->service!=SERVICE_AUDIO ||
           f->railing_id!=RAILING_ID || f->payload_len!=13)return false;
        protocol_frame_t query=*f;
        query.cmd=CMD_SET;query.payload_len=9;
        if(!voice_session_readiness(&query,reply))return false;
        reply->payload[0]=AUDIO_DATA_HEALTH;
        memcpy(reply->payload+12,f->payload+9,4);reply->payload_len=16;
        return true;
    }
    if(f->src!=NODE_P4 || f->railing_id!=RAILING_ID ||
       (f->cmd!=CMD_START && f->cmd!=CMD_STOP && f->cmd!=CMD_SET) ||
       f->payload_len!=(f->cmd==CMD_SET?9:4)) return false;
    uint32_t id=session_id(f->payload+(f->cmd==CMD_SET?1:0));
    uint32_t request=f->cmd==CMD_SET?session_id(f->payload+5):0;
    uint8_t direction=f->cmd==CMD_SET?f->payload[0]:(f->cmd==CMD_START?AUDIO_DIR_FIELD_TX:0);
    bool quiet=!emergency_alert_is_active() && (!music_player_is_playing() || music_player_is_paused());
    portENTER_CRITICAL(&s_lock);
    bool match=id && id==s_session && (f->cmd!=CMD_SET || request==s_ptt_request);
    bool target=f->cmd==CMD_STOP ? !s_active : s_active && s_direction==direction;
    if(f->cmd==CMD_STOP && !s_active)match=true;
    uint8_t status=0;
    if(!match || !target || s_output_state==VOICE_OUTPUT_FAILED)status=2;
    else if(direction==AUDIO_DIR_CONTROL_TX)status=s_output_state==VOICE_OUTPUT_READY?1:0;
    else status=!s_output_busy && s_output_state==VOICE_OUTPUT_IDLE &&
        (f->cmd==CMD_STOP || quiet)?1:0;
    portEXIT_CRITICAL(&s_lock);
    memset(reply,0,sizeof(*reply));
    reply->railing_id=RAILING_ID;reply->src=NODE_WROOM;reply->dst=NODE_P4;
    reply->service=SERVICE_AUDIO;reply->cmd=CMD_DATA;reply->payload_len=12;
    reply->payload[0]=AUDIO_DATA_READY;reply->payload[1]=f->cmd;
    reply->payload[2]=direction;reply->payload[3]=status;
    memcpy(reply->payload+4,f->payload+(f->cmd==CMD_SET?1:0),4);
    if(f->cmd==CMD_SET)memcpy(reply->payload+8,f->payload+5,4);
    return true;
}
