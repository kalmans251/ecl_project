#include "music_eq.h"
#include "music_eq_analyzer.h"
#include "protocol.h"
#include "board_config.h"
#include "router.h"
#include "voice_session.h"
#include "esp_log.h"
#include "esp_timer.h"
static music_eq_analyzer_t s_analyzer;
static unsigned s_sent, s_dropped;
static int64_t s_max_us;

static void send_levels(const uint8_t levels[8])
{
    if (voice_session_is_active()) return;
    protocol_frame_t frame;
    protocol_frame_init(&frame, RAILING_ID, NODE_WROOM, NODE_P4, SERVICE_LED, CMD_DATA);
    frame.payload_len=8;
    for (unsigned i=0;i<8;++i) frame.payload[i]=levels[i];
    /* Display data may be dropped; never block MP3 playback for EQ. */
    if (router_try_enqueue(&frame)) ++s_sent;
    else ++s_dropped;
}
void music_eq_reset(void) { music_eq_analyzer_reset(&s_analyzer); }
void music_eq_clear(void)
{
    uint8_t zero[8]={0};
    send_levels(zero);
    music_eq_reset();
}
void music_eq_feed(const int16_t *pcm, size_t samples, unsigned rate, unsigned volume)
{
    if (voice_session_is_active()) return;
    uint8_t levels[8];
    int64_t start=esp_timer_get_time();
    bool ready=music_eq_analyze(&s_analyzer,pcm,samples/2,rate,volume,levels);
    int64_t elapsed=esp_timer_get_time()-start;
    if (elapsed>s_max_us) s_max_us=elapsed;
    if (!ready) return;
    unsigned previous_sent=s_sent;
    send_levels(levels);
    if (s_sent!=previous_sent && (s_sent==1 || (s_sent && s_sent%50==0)))
        ESP_LOGI("MUSIC_EQ", "sent=%u dropped=%u analysis_max_us=%lld levels=%u,%u,%u,%u,%u,%u,%u,%u",
            s_sent,s_dropped,(long long)s_max_us,levels[0],levels[1],levels[2],levels[3],
            levels[4],levels[5],levels[6],levels[7]);
}
