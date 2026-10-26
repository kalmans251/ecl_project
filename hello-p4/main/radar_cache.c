#include "radar_cache.h"
#include "esp_timer.h"
#include <string.h>

static uint8_t source, count, points[12];
static uint32_t sequence;
static int64_t sampled_us;
static bool sampled;
static unsigned zero_streak;

bool radar_cache_capture(const protocol_frame_t *f)
{
    if(f->src != NODE_S3 || f->dst != NODE_P4 || f->service != SERVICE_RADAR || f->command != CMD_DATA) return false;
    /* Version 1 local sample: type, selected sensor, count, three 8-byte slots. */
    if(f->length != 27 || f->payload[0] != 1 || f->payload[1] < 1 || f->payload[1] > 2 || f->payload[2] > 3) return true;
    uint8_t compact[12] = {0}, n = 0;
    for(int i=0;i<3;i++) {
        const uint8_t *p = f->payload+3+i*8;
        bool present=false;
        for(int j=0;j<8;j++) if(p[j]) present=true;
        if(!present) continue;
        int x=(int16_t)((p[0]<<8)|p[1]), y=(int16_t)((p[2]<<8)|p[3]);
        if(x < -10000 || x > 10000 || y < 0 || y > 10000) return true;
        memcpy(compact+n*4,p,4);n++;
    }
    if(n != f->payload[2]) return true;
    if(source != f->payload[1]) zero_streak=0;
    if(n == 0) { if(zero_streak < 3) zero_streak++; }
    else zero_streak=0;
    if(n == 0 && count > 0 && source == f->payload[1] && zero_streak < 3) return true;
    source=f->payload[1];count=n;memcpy(points,compact,12);
    sequence++;sampled_us=esp_timer_get_time();sampled=true;
    return true;
}

bool radar_cache_reply(const protocol_frame_t *q, protocol_frame_t *r)
{
    if(q->src != NODE_PI || q->dst != NODE_P4 || q->service != SERVICE_RADAR || q->command != CMD_STATUS_REQUEST) return false;
    if(q->length != 5 || q->payload[4] > 1) return true;
    *r=(protocol_frame_t){0};r->railing_id=q->railing_id;r->src=NODE_P4;r->dst=NODE_PI;
    r->service=SERVICE_RADAR;r->command=CMD_STATUS_RESPONSE;
    int64_t elapsed=sampled?(esp_timer_get_time()-sampled_us)/1000:65535;
    bool valid=sampled && elapsed>=0 && elapsed<=1500;
    unsigned age=elapsed<0?65535:(elapsed>65535?65535:(unsigned)elapsed);
    /* token4, version, sensor, valid, count, sequence4, age2, detail flag, xy pairs */
    memcpy(r->payload,q->payload,4);r->payload[4]=1;r->payload[5]=source;
    r->payload[6]=valid;r->payload[7]=valid?count:0;
    for(int i=0;i<4;i++) r->payload[8+i]=(uint8_t)(sequence>>(24-i*8));
    r->payload[12]=age>>8;r->payload[13]=age;
    r->payload[14]=q->payload[4];r->length=15;
    if(valid && q->payload[4]) {memcpy(r->payload+15,points,count*4);r->length+=count*4;}
    return true;
}
