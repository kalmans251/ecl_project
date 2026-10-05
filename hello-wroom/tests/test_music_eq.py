from pathlib import Path
import subprocess
import tempfile
import unittest

MAIN=Path(__file__).resolve().parents[1]/'main'
P4=MAIN.parents[1]/'hello-p4'/'main'
HARNESS=r'''
#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <string.h>
#include "music_eq_analyzer.h"
#include "led_eq_fresh.h"
static music_eq_analyzer_t state;
static void tone(float frequency,unsigned rate,unsigned volume,uint8_t bands[8]) {
    (void)volume;
    music_eq_analyzer_reset(&state);
    int16_t pcm[2304]; unsigned sample=0, reports=0;
    for(unsigned block=0;block<rate/512;++block) {
        for(unsigned i=0;i<512;++i) {
            int16_t v=(int16_t)(16000*sinf(6.28318530718f*frequency*(sample++)/rate));
            pcm[i]=v;
        }
        if(music_eq_analyze(&state,pcm,512,rate,bands)) ++reports;
    }
    assert(reports>=8 && reports<=10); // at most 10Hz
}
int main(void) {
    uint8_t bands[8];
    const float frequencies[8]={62.5f,187.5f,375,750,1500,3000,5000,7000};
    for(unsigned rate_i=0;rate_i<3;++rate_i) {
        const unsigned rates[3]={16000,44100,48000};
        for(unsigned band=0;band<8;++band) {
            tone(frequencies[band],rates[rate_i],100,bands);
            for(unsigned other=0;other<8;++other)
                if(other!=band) assert(bands[band]>bands[other]);
        }
    }
    int16_t silence[1600]={0};
    music_eq_analyzer_reset(&state);
    assert(music_eq_analyze(&state,silence,1600,16000,bands));
    for(unsigned i=0;i<8;++i) assert(bands[i]==0);
    uint8_t loud[8];tone(750,44100,100,loud);tone(750,44100,10,bands);
    assert(loud[3]==bands[3]);
    // Very quiet content still spans the display; silence is never normalized up.
    int16_t quiet[1600];
    for(unsigned i=0;i<1600;++i) quiet[i]=(int16_t)(100*sinf(6.28318530718f*750*i/16000));
    music_eq_analyzer_reset(&state);
    for(unsigned i=0;i<10;++i) music_eq_analyze(&state,quiet,1600,16000,bands);
    assert(bands[3]>220);
    for(unsigned i=0;i<10;++i) music_eq_analyze(&state,silence,1600,16000,bands);
    for(unsigned i=0;i<8;++i) assert(bands[i]==0);
    tone(750,8000,100,bands); // low-rate MP3 cannot divide by zero
    assert(bands[3]>0);
    music_eq_analyzer_reset(&state);
    for(unsigned i=0;i<8;++i) assert(state.smoothed[i]==0);
    assert(!led_eq_is_fresh(false,0,0));
    assert(led_eq_is_fresh(true,100,600));
    assert(!led_eq_is_fresh(true,100,601));
    assert(led_eq_is_fresh(true,UINT32_MAX-20,20));
    assert(!led_eq_is_fresh(true,UINT32_MAX-20,600));
    return 0;
}
'''
class MusicEqTests(unittest.TestCase):
    def test_spectrum_rate_gain_silence_and_p4_expiry(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'test.c';source.write_text(HARNESS)
            binary=Path(folder)/'test'
            subprocess.run(['cc','-std=c11','-O2','-Wall','-Wextra','-Werror',
                '-I',str(MAIN),'-I',str(P4),str(source),str(MAIN/'music_eq_analyzer.c'),
                '-lm','-o',str(binary)],check=True)
            subprocess.run([str(binary)],check=True,timeout=10)

WRAPPER_HARNESS=r'''
#include <assert.h>
#include <string.h>
#include "music_eq.c"
static bool active, accepting=true;
static protocol_frame_t captured;
static unsigned attempts, notifications;
static bool allocation_ok=true, invalidate;
BaseType_t xTaskCreate(void (*fn)(void *),const char *name,unsigned stack,void *arg,unsigned priority,TaskHandle_t *task) {
    (void)fn;(void)name;(void)stack;(void)arg;assert(priority==1);
    *task=allocation_ok?(void *)1:NULL;return allocation_ok?pdPASS:0;
}
void xTaskNotifyGive(TaskHandle_t task) { assert(task);++notifications; }
unsigned ulTaskNotifyTake(int clear,unsigned timeout) { (void)clear;(void)timeout;return 1; }
int64_t esp_timer_get_time(void) { static int64_t t; t+=100; if(invalidate) { invalidate=false; music_eq_reset(); } return t; }
bool voice_session_is_active(void) { return active; }
bool router_try_enqueue(const protocol_frame_t *p) {
    ++attempts; captured=*p; return accepting;
}
int main(void) {
    int16_t pcm[1024]={0};
    allocation_ok=false; assert(!music_eq_init());
    music_eq_feed(pcm,1024,16000);assert(notifications==0);
    allocation_ok=true; assert(music_eq_init());
    music_eq_reset();
    music_eq_feed(pcm,1024,16000);
    music_eq_feed(pcm,1024,16000);
    assert(s_overwritten==1 && attempts==0); // producer never runs FFT or sends
    pcm[0]=1234;assert(s_pending.pcm[0]==0); // copied PCM is independent
    process_pending();
    for(int i=0;i<3;++i) { music_eq_feed(pcm,1024,16000);process_pending(); }
    assert(attempts==1 && s_sent==1);
    assert(captured.src==NODE_WROOM && captured.dst==NODE_P4);
    assert(captured.service==SERVICE_LED && captured.cmd==CMD_DATA && captured.payload_len==8);
    music_eq_clear();
    assert(attempts==2);
    for(unsigned i=0;i<8;++i) assert(captured.payload[i]==0);
    accepting=false;
    for(int i=0;i<4;++i) { music_eq_feed(pcm,1024,16000);process_pending(); }
    assert(s_dropped==1);
    accepting=true;
    music_eq_reset();
    music_eq_feed(pcm,1024,16000);music_eq_clear();
    unsigned cleared=attempts;process_pending();assert(attempts==cleared);
    for(int i=0;i<3;++i) { music_eq_feed(pcm,1024,16000);process_pending(); }
    music_eq_feed(pcm,1024,16000);invalidate=true;
    process_pending();assert(attempts==cleared); // reset while analysis in flight
    active=true;
    unsigned old=attempts;
    for(int i=0;i<8;++i) music_eq_feed(pcm,1024,16000);
    music_eq_clear();
    assert(attempts==old); // no EQ traffic during calls
    return 0;
}
'''

class EqTransportTests(unittest.TestCase):
    def test_payload_rate_queue_failure_clear_and_call_suppression(self):
        from test_audio_output import HEADERS
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for name, text in HEADERS.items():
                p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
            (root/'freertos/FreeRTOS.h').write_text(HEADERS['freertos/FreeRTOS.h']+'\ntypedef int BaseType_t;\n#define pdPASS 1\n#define pdTRUE 1\n')
            (root/'freertos/task.h').write_text('''#pragma once
#include "FreeRTOS.h"
BaseType_t xTaskCreate(void (*)(void *),const char *,unsigned,void *,unsigned,TaskHandle_t *);
void xTaskNotifyGive(TaskHandle_t);
unsigned ulTaskNotifyTake(int,unsigned);
''')
            (root/'esp_log.h').write_text('#define ESP_LOGI(tag,...) ((void)(tag))\n#define ESP_LOGW(tag,...) ((void)(tag))\n')
            (root/'esp_timer.h').write_text('#include <stdint.h>\nint64_t esp_timer_get_time(void);\n')
            source=root/'test.c';source.write_text(WRAPPER_HARNESS)
            binary=root/'test'
            subprocess.run(['cc','-std=c11','-O2','-Wall','-Wextra','-Werror',
                '-I',str(root),'-I',str(MAIN),str(source),str(MAIN/'music_eq_analyzer.c'),
                str(MAIN/'protocol.c'),'-lm','-o',str(binary)],check=True)
            subprocess.run([str(binary)],check=True,timeout=5)
