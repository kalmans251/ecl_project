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
static protocol_frame_t last;
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
int main(void) {
    now=100;system_state_init();call_manager_init();
    assert(!call_manager_end_recovery_active());
    assert(call_manager_start(CALL_ORIGIN_EMERGENCY));
    assert(call_manager_end());
    assert(last.dst==NODE_PI && last.payload[1]==AUDIO_EVENT_CALL_ENDED);
    assert(last.payload[2]==CALL_ORIGIN_EMERGENCY);
    assert(call_manager_end_recovery_active());
    unsigned before=sent, r=restores, m=removes;
    assert(call_manager_end());
    assert(sent==before+1 && restores==r && removes==m);
    assert(last.payload[2]==CALL_ORIGIN_EMERGENCY);
    now+=END_RECOVERY_US;
    assert(!call_manager_end_recovery_active());
    assert(call_manager_end());assert(call_manager_end_recovery_active());
    assert(call_manager_start(CALL_ORIGIN_NORMAL));
    assert(!call_manager_end_recovery_active());
    assert(call_manager_end());assert(last.payload[2]==CALL_ORIGIN_NORMAL);
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
