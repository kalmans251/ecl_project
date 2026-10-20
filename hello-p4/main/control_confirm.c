#include <string.h>
#include "control_confirm.h"
#include "freertos/task.h"
#include "router.h"
static portMUX_TYPE mux=portMUX_INITIALIZER_UNLOCKED;
static TaskHandle_t owner;
static protocol_frame_t request;
static bool forwarded;
void control_confirm_begin(const protocol_frame_t *f) {
    portENTER_CRITICAL(&mux);request=*f;forwarded=false;owner=xTaskGetCurrentTaskHandle();portEXIT_CRITICAL(&mux);
}
bool control_confirm_end(void) {
    portENTER_CRITICAL(&mux);bool result=forwarded;owner=NULL;portEXIT_CRITICAL(&mux);return result;
}
bool control_confirm_send_music(protocol_frame_t *f,TickType_t wait) {
    bool matched=false;
    portENTER_CRITICAL(&mux);
    if(owner==xTaskGetCurrentTaskHandle() && request.length==f->length+5 &&
       request.payload[4]==f->command && !memcmp(request.payload+5,f->payload,f->length)) {
        memmove(f->payload+5,f->payload,f->length);memcpy(f->payload,request.payload,5);
        f->command=CMD_APPLY;f->length+=5;f->railing_id=request.railing_id;matched=true;
    }
    portEXIT_CRITICAL(&mux);
    bool ok=xQueueSend(router_queue,f,wait)==pdTRUE;
    if(matched && ok){portENTER_CRITICAL(&mux);forwarded=true;portEXIT_CRITICAL(&mux);}
    return ok;
}
