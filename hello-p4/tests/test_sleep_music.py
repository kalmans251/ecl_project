"""Exercise real sleep, music manager and pause policy across LED-mode wake."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from test_control_window import HEADERS

MAIN=Path(__file__).resolve().parents[1]/'main'
HARNESS=r'''
#include <assert.h>
#include <string.h>
#include "sleep_manager.c"
#include "music_policy.h"
static int64_t clock_us;
static bool projector;
static unsigned commands;
static uint8_t last_command;
QueueHandle_t router_queue=(void *)1;
int64_t esp_timer_get_time(void) { return clock_us; }
void projector_control_set(bool enabled) { projector=enabled; }
void detection_manager_get_summary(detection_summary_t *summary) { memset(summary,0,sizeof(*summary)); }
SemaphoreHandle_t xSemaphoreCreateMutex(void) { return (void *)1; }
int xSemaphoreTake(SemaphoreHandle_t handle,unsigned wait) { (void)handle;(void)wait;return 1; }
int xSemaphoreGive(SemaphoreHandle_t handle) { (void)handle;return 1; }
int xQueueSend(QueueHandle_t queue,const void *data,TickType_t wait) {
    (void)wait;assert(queue==router_queue);
    const protocol_frame_t *frame=data;
    assert(frame->src==NODE_P4 && frame->dst==NODE_WROOM && frame->service==SERVICE_MUSIC);
    last_command=frame->command;++commands;return pdTRUE;
}
static void setup(void) {
    clock_us=0;commands=0;projector=true;
    system_state_init();sleep_manager_init();music_policy_init();music_manager_init();
    system_state_set_projector_enabled(true);
    system_state_set_led_mode(LED_MODE_MUSIC);
    sleep_manager_set_enabled(true);
    assert(music_manager_start());assert(last_command==CMD_START);
    music_policy_on_started();
}
static void sleep_via_led(bool pause_ack) {
    // Fixture: idle timeout elapsed while waiting for the current track to finish.
    s_activity=ACTIVITY_SLEEP_PENDING;clock_us=11000000;
    system_state_set_led_mode(LED_MODE_BASIC);
    music_policy_add_pause_reason(MUSIC_PAUSE_REASON_LED);
    assert(last_command==CMD_PAUSE);
    if(pause_ack) music_policy_on_paused();
    sleep_manager_on_led_mode_changed(LED_MODE_BASIC);
    assert(sleep_manager_get_state()==ACTIVITY_SLEEPING && !projector);
    unsigned before=commands;
    system_state_set_led_mode(LED_MODE_MUSIC);
    music_policy_remove_pause_reason(MUSIC_PAUSE_REASON_LED);
    music_manager_on_led_mode_changed(LED_MODE_MUSIC);
    assert(commands==before); // no playback while asleep
}
static void radar_wake(void) {
    sleep_manager_on_new_detection(DETECTION_SOURCE_RADAR,1,false);
    assert(sleep_manager_get_state()==ACTIVITY_ACTIVE && projector);
    music_manager_on_wake();
}
int main(void) {
    setup();sleep_via_led(true);
    unsigned before=commands;radar_wake();
    assert(commands==before+1 && last_command==CMD_RESUME);
    music_policy_on_resumed();p4_system_state_t state;system_state_get(&state);
    assert(state.music_playing && !state.sleep_active);
    setup();sleep_via_led(false);before=commands;radar_wake();
    assert(commands==before+1 && last_command==CMD_RESUME); // delayed PAUSED event
    const music_pause_reason_t blocked[]={MUSIC_PAUSE_REASON_USER,MUSIC_PAUSE_REASON_CALL,MUSIC_PAUSE_REASON_EMERGENCY};
    for(unsigned i=0;i<3;++i) {
        setup();sleep_via_led(true);music_policy_add_pause_reason(blocked[i]);
        before=commands;radar_wake();assert(commands==before);
        music_policy_remove_pause_reason(blocked[i]);assert(last_command==CMD_RESUME);
    }
    setup();sleep_via_led(true);music_manager_stop();before=commands;
    radar_wake();assert(commands==before); // stopped session stays stopped
    setup();music_policy_on_finished();enter_sleeping();
    music_manager_on_track_finished(true);before=commands;radar_wake();
    assert(commands==before+1 && last_command==CMD_NEXT); // completed track advances
    setup();music_manager_stop();music_policy_on_stopped();enter_sleeping();
    assert(music_manager_start());before=commands;radar_wake();
    assert(commands==before+1 && last_command==CMD_START); // armed empty session starts
    setup();sleep_via_led(true);system_state_set_led_mode(LED_MODE_WEATHER);
    before=commands;radar_wake();assert(commands==before); // non-music mode stays quiet
    setup();sleep_via_led(true);before=commands;music_manager_on_wake();
    assert(commands==before); // do not resume before actual wake
    return 0;
}
'''
class SleepMusicTests(unittest.TestCase):
    def test_led_pause_sleep_and_radar_wake(self):
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
                str(source),str(MAIN/'music_manager.c'),str(MAIN/'music_policy.c'),
                str(MAIN/'system_state.c'),'-Wl,--gc-sections','-o',str(binary)],check=True)
            subprocess.run([str(binary)],check=True,timeout=5)
