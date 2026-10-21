"""Exercise real call-manager duplicate STOP and bounded recovery state."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from test_control_window import HEADERS
MAIN=Path(__file__).resolve().parents[1]/'main'
HARNESS=r'''

#include <assert.h>
#include "call_manager.c"
static int64_t now;
static unsigned sent, restores, removes;
static protocol_frame_t last, terminal;
static unsigned terminal_count;
void event_outbox_store_call_end(const protocol_frame_t *f){terminal=*f;terminal_count++;}
void event_outbox_clear_call_end(void){terminal_count=0;}
QueueHandle_t router_queue=(void *)1;
int64_t esp_timer_get_time(void) { return now; }
SemaphoreHandle_t xSemaphoreCreateMutex(void) { return (void *)1; }
int xSemaphoreTake(SemaphoreHandle_t h,unsigned w) { (void)h;(void)w;return 1; }
int xSemaphoreGive(SemaphoreHandle_t h) { (void)h;return 1; }
int xQueueSend(QueueHandle_t q,const void *f,TickType_t t) {
    (void)t;assert(q==router_queue);last=*(const protocol_frame_t *)f;++sent;return pdTRUE;
}
void projector_control_set(bool enabled) { (void)enabled;++restores; }
void music_policy_add_pause_reason(music_pause_reason_t reason) { (void)reason; }
void music_policy_remove_pause_reason(music_pause_reason_t reason) { (void)reason;++removes; }
static void report(uint8_t node, uint8_t status) {
    protocol_frame_t f={.railing_id=RAILING_ID,.src=node,.dst=NODE_P4,
        .service=SERVICE_AUDIO,.command=CMD_DATA,.length=12,
        .payload={AUDIO_DATA_READY}};
    f.payload[1]=s_operation;f.payload[2]=s_target;f.payload[3]=status;
    put_session(f.payload+4,s_session);put_session(f.payload+8,s_operation==CMD_SET?s_ptt_request:0);
    call_manager_handle_readiness(&f);
}
static void both(void){report(NODE_WROOM,1);report(NODE_S3,1);}
int main(void) {
    now=100;system_state_init();call_manager_init();
    assert(call_manager_bind_session(101));
    assert(call_manager_start(CALL_ORIGIN_EMERGENCY));
    assert(s_preparing && sent==2 && last.dst!=NODE_PI);
    assert(call_manager_control_grants_enabled());
    protocol_frame_t voice={.railing_id=RAILING_ID,.src=NODE_S3,.dst=NODE_PI,
      .service=SERVICE_AUDIO,.command=CMD_DATA,.length=59,
      .payload={AUDIO_DATA_CODEC2,1,AUDIO_DIRECTION_FIELD_TX,0,0,8,6,0,0,0,101}};
    assert(!call_manager_voice_allowed(&voice));
    report(NODE_WROOM,1);unsigned before=sent;
    assert(!call_manager_bind_session(101));assert(sent==before);
    report(NODE_S3,1);assert(sent==before); // never unsolicited PLC confirmation
    assert(!call_manager_bind_session(101));
    assert(last.dst==NODE_PI && last.payload[1]==AUDIO_EVENT_CALL_STARTED);
    assert(call_manager_voice_allowed(&voice));
    assert(!call_manager_bind_session(202));assert(!call_manager_stop_session(202));
    assert(call_manager_set_direction_ordered(101,1,AUDIO_DIRECTION_CONTROL_TX));
    assert(call_manager_get_state()==CALL_STATE_FIELD_TX); // grants remain available to the retry
    assert(!call_manager_voice_allowed(&voice));
    assert(!call_manager_set_direction_ordered(101,1,AUDIO_DIRECTION_FIELD_TX));
    both();assert(call_manager_set_direction_ordered(101,1,AUDIO_DIRECTION_CONTROL_TX));
    assert(last.payload[1]==AUDIO_EVENT_DIRECTION_CHANGED && last.payload[11]==1);
    assert(call_manager_get_state()==CALL_STATE_CONTROL_TX);
    assert(!call_manager_control_grants_enabled());
    voice.src=NODE_PI;voice.dst=NODE_WROOM;voice.payload[2]=AUDIO_DIRECTION_CONTROL_TX;
    assert(call_manager_voice_allowed(&voice));
    assert(call_manager_set_direction_ordered(101,2,AUDIO_DIRECTION_FIELD_TX));
    assert(call_manager_get_state()==CALL_STATE_CONTROL_TX && call_manager_control_grants_enabled());
    // Delayed report from the prior PTT cannot complete this operation.
    protocol_frame_t old={.railing_id=RAILING_ID,.src=NODE_S3,.dst=NODE_P4,
        .service=SERVICE_AUDIO,.command=CMD_DATA,.length=12,
        .payload={AUDIO_DATA_READY,CMD_SET,AUDIO_DIRECTION_CONTROL_TX,1}};
    put_session(old.payload+4,101);put_session(old.payload+8,1);
    call_manager_handle_readiness(&old);assert(s_ready_mask==0);
    both();assert(call_manager_set_direction_ordered(101,2,AUDIO_DIRECTION_FIELD_TX));
    assert(!call_manager_set_direction_ordered(101,1,AUDIO_DIRECTION_CONTROL_TX));
    assert(call_manager_stop_session(101));assert(call_manager_is_active());
    unsigned m=removes;report(NODE_WROOM,1);
    assert(!call_manager_stop_session(101));assert(removes==m && terminal_count==0);
    report(NODE_S3,1);assert(call_manager_stop_session(101));
    assert(!call_manager_is_active() && removes==m+1 && terminal_count==1);
    assert(!call_manager_control_grants_enabled());
    assert(last.payload[1]==AUDIO_EVENT_CALL_ENDED && last.payload[2]==CALL_ORIGIN_EMERGENCY);
    before=sent;m=removes;assert(call_manager_stop_session(101));assert(sent==before+1 && removes==m);
    assert(!call_manager_bind_session(101));
    assert(call_manager_bind_session(202));assert(call_manager_start(CALL_ORIGIN_NORMAL));
    report(NODE_S3,2);assert(!call_manager_bind_session(202));
    assert(last.length==14 && last.payload[1]==4 && last.payload[12]==NODE_S3);
    assert(s_preparing && !call_manager_voice_allowed(&voice));
    assert(call_manager_stop_session(202));both();assert(call_manager_stop_session(202));
    assert(call_manager_bind_session(203));assert(call_manager_start(CALL_ORIGIN_NORMAL));
    now+=4000000;call_manager_tick();assert(s_failed_reason==3);
    assert(!call_manager_bind_session(203));assert(last.payload[13]==3);
    now+=CALL_LEASE_US;call_manager_tick();assert(s_operation==CMD_STOP && call_manager_is_active());
    both();before=sent;call_manager_tick();assert(!call_manager_is_active());
    assert(sent==before && terminal.payload[1]==AUDIO_EVENT_CALL_ENDED); // retained END, no unsolicited send
    assert(call_manager_stop_session(303));assert(call_manager_is_active());
    both();assert(call_manager_stop_session(303));assert(last.payload[6]==1 && last.payload[7]==47);
    return 0;
}
'''
class HangupTests(unittest.TestCase):
    def test_duplicate_stop_and_recovery_expiration(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for name,text in HEADERS.items():
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text)
            (root/'freertos/FreeRTOS.h').write_text(HEADERS['freertos/FreeRTOS.h']+'\n#include <stdlib.h>\n')
            (root/'freertos/semphr.h').write_text('''#pragma once
#include "FreeRTOS.h"
typedef void *SemaphoreHandle_t;
SemaphoreHandle_t xSemaphoreCreateMutex(void);
int xSemaphoreTake(SemaphoreHandle_t,unsigned);
int xSemaphoreGive(SemaphoreHandle_t);
''')
            (root/'freertos/task.h').write_text('#pragma once\nvoid vTaskDelay(unsigned);\n')
            (root/'esp_log.h').write_text('''#define ESP_LOGI(tag,...) ((void)(tag))
#define ESP_LOGW(tag,...) ((void)(tag))
#define ESP_LOGE(tag,...) ((void)(tag))
''')
            source=root/'test.c';source.write_text(HARNESS)
            binary=root/'test'
            subprocess.run(['cc','-std=c11','-O2','-Wall','-Wextra','-Werror',
                '-ffunction-sections','-fdata-sections','-I',str(root),'-I',str(MAIN),
                str(source),
                str(MAIN/'system_state.c'),'-Wl,--gc-sections','-o',str(binary)],check=True)
            subprocess.run([str(binary)],check=True,timeout=5)
