#include "voice_session.h"
#include "audio_output.h"
#include "music_player.h"
#include "emergency_alert.h"
#include "codec2.h"
#include "esp_log.h"
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
static audio_direction_t s_direction = AUDIO_DIR_FIELD_TX;
static uint32_t s_generation;
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
    portEXIT_CRITICAL(&s_lock);
}

/* Stereo I2S: duplicate each of the 160 mono samples into L/R. */
static bool write_frame(const int16_t *mono, uint32_t generation)
{
    if (!control_active(generation)) return false;
    int16_t stereo[320];
    for (unsigned i = 0; i < 160; ++i) {
        stereo[2*i] = mono ? mono[i] : 0;
        stereo[2*i+1] = mono ? mono[i] : 0;
    }
    bool ok = audio_output_write(stereo, 320);
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
    voice_packet_t packet;
    while (1) {
        if (decoder && !control_active(generation)) {
            if (restore_rate) audio_output_set_sample_rate(restore_rate);
            else audio_output_deinit();
            codec2_destroy(decoder);
            decoder = NULL;
            audio_output_release();
            output_busy(false);
        }
        if (xQueueReceive(s_packets, &packet, decoder ? 0 : pdMS_TO_TICKS(20)) != pdTRUE) {
            if (decoder) {
                ++underflows;
                write_frame(NULL, generation);
                if (underflows == 1 || underflows % 50 == 0)
                    ESP_LOGW(TAG, "Voice buffer empty blocks=%u", underflows);
            }
            continue;
        }
        if (!control_active(packet.generation)) continue;
        if (!decoder) {
            generation = packet.generation;
            output_busy(true);
            if (!audio_output_claim()) {
                output_busy(false);
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
                audio_output_release();
                output_busy(false);
                continue;
            }
            decoder = codec2_create(CODEC2_MODE_2400);
            if (!decoder || codec2_samples_per_frame(decoder) != 160
                    || codec2_bits_per_frame(decoder) != 48 || !audio_output_init(8000)) {
                if (decoder) codec2_destroy(decoder);
                decoder = NULL;
                if (restore_rate) audio_output_set_sample_rate(restore_rate);
                else audio_output_deinit();
                audio_output_release();
                output_busy(false);
                ESP_LOGE(TAG, "Codec2/I2S initialization failed");
                continue;
            }
            have_sequence = false;
            packets = missing = underflows = 0;
            /* Hold first packet until two more arrive, or 600ms elapses. */
            for (unsigned i = 0; i < 60 && uxQueueMessagesWaiting(s_packets) < 2
                    && control_active(generation); ++i)
                vTaskDelay(pdMS_TO_TICKS(10));
            ESP_LOGI(TAG, "Codec2 playback 8000Hz stereo I2S ready");
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
        for (unsigned i = 0; i < packet.frames && control_active(generation); ++i) {
            codec2_decode(decoder, mono, packet.data + i * 6);
            if (!write_frame(mono, generation)) {
                ESP_LOGW(TAG, "Voice I2S write failed/interrupted");
                break;
            }
        }
        ++packets;
        if (packets == 1 || packets % 25 == 0)
            ESP_LOGI(TAG, "Codec2 PLAY seq=%u packets=%u missing=%u empty=%u queued=%u stack_free_bytes=%u",
                     packet.sequence, packets, missing, underflows,
                     (unsigned)uxQueueMessagesWaiting(s_packets),
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
    if (changed) ++s_generation;
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
    ESP_LOGI(TAG, "CALL START -> FIELD_TX");
}
void voice_session_stop(void) {
    change_session(false, AUDIO_DIR_FIELD_TX);
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
    bool active = session_active && session_direction == AUDIO_DIR_CONTROL_TX;
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
