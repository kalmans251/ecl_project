#include "music_eq.h"
#include "music_eq_analyzer.h"
#include "protocol.h"
#include "board_config.h"
#include "router.h"
#include "voice_session.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include <string.h>

/* One MP3 frame, already reduced to mono. No dynamic PCM queues. */
#define EQ_MAX_FRAMES 1152U
typedef struct {
    int16_t pcm[EQ_MAX_FRAMES];
    size_t frames;
    unsigned rate, epoch;
} eq_block_t;
static eq_block_t s_pending, s_work;
static portMUX_TYPE s_lock=portMUX_INITIALIZER_UNLOCKED;
static TaskHandle_t s_task;
static unsigned s_epoch, s_worker_epoch, s_overwritten;
static music_eq_analyzer_t s_analyzer;
static unsigned s_sent, s_dropped;
static int64_t s_max_us;

static void send_levels(const uint8_t levels[8])
{
    if (voice_session_is_active()) return;
    protocol_frame_t frame;
    protocol_frame_init(&frame, RAILING_ID, NODE_WROOM, NODE_P4, SERVICE_LED, CMD_DATA);
    frame.payload_len=8;
    memcpy(frame.payload,levels,8);
    if (router_try_enqueue(&frame)) ++s_sent;
    else ++s_dropped;
}

static void process_pending(void)
{
    portENTER_CRITICAL(&s_lock);
    s_work=s_pending;
    s_pending.frames=0;
    unsigned epoch=s_epoch;
    portEXIT_CRITICAL(&s_lock);
    if (s_worker_epoch!=epoch) {
        music_eq_analyzer_reset(&s_analyzer);
        s_worker_epoch=epoch;
    }
    if (!s_work.frames || s_work.epoch!=epoch || voice_session_is_active()) return;
    uint8_t levels[8];
    int64_t start=esp_timer_get_time();
    bool ready=music_eq_analyze(&s_analyzer,s_work.pcm,s_work.frames,s_work.rate,levels);
    int64_t elapsed=esp_timer_get_time()-start;
    if (elapsed>s_max_us) s_max_us=elapsed;
    portENTER_CRITICAL(&s_lock);
    bool current=s_work.epoch==s_epoch;
    unsigned overwritten=s_overwritten;
    portEXIT_CRITICAL(&s_lock);
    if (!ready || !current) return;
    unsigned previous=s_sent;
    send_levels(levels);
    if (s_sent!=previous && (s_sent==1 || s_sent%50==0))
        ESP_LOGI("MUSIC_EQ", "sent=%u dropped=%u overwritten=%u analysis_max_us=%lld levels=%u,%u,%u,%u,%u,%u,%u,%u",
            s_sent,s_dropped,overwritten,(long long)s_max_us,levels[0],levels[1],levels[2],levels[3],
            levels[4],levels[5],levels[6],levels[7]);
    (void)overwritten;
}
static void eq_task(void *arg)
{
    (void)arg;
    for (;;) {
        ulTaskNotifyTake(pdTRUE,portMAX_DELAY);
        process_pending();
    }
}
bool music_eq_init(void)
{
    if (s_task) return true;
    if (xTaskCreate(eq_task,"music_eq",3072,NULL,1,&s_task)!=pdPASS) {
        s_task=NULL;
        ESP_LOGW("MUSIC_EQ","Worker allocation failed; music continues without EQ");
        return false;
    }
    return true;
}
void music_eq_reset(void)
{
    portENTER_CRITICAL(&s_lock);
    ++s_epoch;
    s_pending.frames=0;
    portEXIT_CRITICAL(&s_lock);
    if (s_task) xTaskNotifyGive(s_task);
}
void music_eq_clear(void)
{
    music_eq_reset();
    uint8_t zero[8]={0};
    /* Only the EQ task owns FFT state and telemetry counters. */
    if (!voice_session_is_active()) {
        protocol_frame_t frame;
        protocol_frame_init(&frame,RAILING_ID,NODE_WROOM,NODE_P4,SERVICE_LED,CMD_DATA);
        frame.payload_len=8;
        memcpy(frame.payload,zero,8);
        router_try_enqueue(&frame);
    }
}
void music_eq_feed(const int16_t *pcm, size_t samples, unsigned rate)
{
    if (!s_task || !pcm || !samples || samples%2 || samples/2>EQ_MAX_FRAMES
            || rate<8000 || rate>48000 || voice_session_is_active()) return;
    portENTER_CRITICAL(&s_lock);
    if (s_pending.frames) ++s_overwritten;
    s_pending.frames=samples/2;
    s_pending.rate=rate;
    s_pending.epoch=s_epoch;
    for (size_t i=0;i<s_pending.frames;++i)
        s_pending.pcm[i]=(int16_t)(((int32_t)pcm[2*i]+pcm[2*i+1])/2);
    portEXIT_CRITICAL(&s_lock);
    xTaskNotifyGive(s_task);
}
