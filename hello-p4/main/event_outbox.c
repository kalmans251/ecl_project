#include <string.h>
#include "event_outbox.h"
#include "freertos/FreeRTOS.h"
#include "esp_random.h"
#include "esp_log.h"
#define CAPACITY 32
static portMUX_TYPE mux = portMUX_INITIALIZER_UNLOCKED;
static struct { uint32_t id; uint8_t command, payload[5]; } entries[CAPACITY];
static unsigned head, count;
static uint32_t next_id, dropped;
static void put32(uint8_t *p, uint32_t n) {
    p[0]=n>>24;p[1]=n>>16;p[2]=n>>8;p[3]=n;
}
static uint32_t get32(const uint8_t *p) {
    return ((uint32_t)p[0]<<24)|((uint32_t)p[1]<<16)|((uint32_t)p[2]<<8)|p[3];
}
bool event_outbox_capture(const protocol_frame_t *f) {
    if(f->src!=NODE_P4 || f->dst!=NODE_PI || f->service!=SERVICE_EMERGENCY ||
       (f->command!=CMD_START && f->command!=CMD_STOP) || f->length!=5)return false;
    uint32_t seed=esp_random();
    portENTER_CRITICAL(&mux);
    if(!next_id)next_id=seed?seed:1;
    bool full=count==CAPACITY;
    if(full) { if(dropped!=UINT32_MAX)++dropped; }
    else {
        unsigned i=(head+count)%CAPACITY;
        if(++next_id==0)++next_id;
        entries[i].id=next_id;entries[i].command=f->command;
        memcpy(entries[i].payload,f->payload,5);++count;
    }
    portEXIT_CRITICAL(&mux);
    if(full)ESP_LOGE("EVENT_OUTBOX","Emergency report queue full; loss counter increased");
    return true;
}
void event_outbox_reply(const protocol_frame_t *poll, protocol_frame_t *reply) {
    memset(reply,0,sizeof(*reply));
    reply->railing_id=poll->railing_id;reply->src=NODE_P4;reply->dst=NODE_PI;
    reply->service=SERVICE_SYSTEM;reply->command=CMD_EVENT_REPLY;reply->length=14;
    memcpy(reply->payload,poll->payload,4);
    portENTER_CRITICAL(&mux);
    uint32_t ack=get32(poll->payload+4);
    if(count && ack==entries[head].id){head=(head+1)%CAPACITY;--count;}
    put32(reply->payload+8,dropped);
    if(count){
        put32(reply->payload+4,entries[head].id);
        reply->payload[12]=SERVICE_EMERGENCY;reply->payload[13]=entries[head].command;
        memcpy(reply->payload+14,entries[head].payload,5);reply->length=19;
    }
    portEXIT_CRITICAL(&mux);
}
