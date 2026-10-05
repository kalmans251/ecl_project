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
    music_eq_analyzer_reset(&state);
    int16_t pcm[2304]; unsigned sample=0, reports=0;
    for(unsigned block=0;block<rate/512;++block) {
        for(unsigned i=0;i<512;++i) {
            int16_t v=(int16_t)(16000*sinf(6.28318530718f*frequency*(sample++)/rate));
            pcm[2*i]=pcm[2*i+1]=v;
        }
        if(music_eq_analyze(&state,pcm,512,rate,volume,bands)) ++reports;
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
    tone(1000,48000,0,bands);
    for(unsigned i=0;i<8;++i) assert(bands[i]==0);
    uint8_t loud[8];tone(750,44100,100,loud);tone(750,44100,10,bands);
    assert(loud[3]>bands[3]);
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
static unsigned attempts;
int64_t esp_timer_get_time(void) { static int64_t t; t+=100; return t; }
bool voice_session_is_active(void) { return active; }
bool router_try_enqueue(const protocol_frame_t *p) {
    ++attempts; captured=*p; return accepting;
}
int main(void) {
    int16_t pcm[1024]={0};
    music_eq_reset();
    for(int i=0;i<4;++i) music_eq_feed(pcm,1024,16000,100);
    assert(attempts==1 && s_sent==1);
    assert(captured.src==NODE_WROOM && captured.dst==NODE_P4);
    assert(captured.service==SERVICE_LED && captured.cmd==CMD_DATA && captured.payload_len==8);
    music_eq_clear();
    assert(attempts==2);
    for(unsigned i=0;i<8;++i) assert(captured.payload[i]==0);
    accepting=false;
    for(int i=0;i<4;++i) music_eq_feed(pcm,1024,16000,100);
    assert(s_dropped==1);
    active=true;
    unsigned old=attempts;
    for(int i=0;i<8;++i) music_eq_feed(pcm,1024,16000,100);
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
            (root/'esp_timer.h').write_text('#include <stdint.h>\nint64_t esp_timer_get_time(void);\n')
            source=root/'test.c';source.write_text(WRAPPER_HARNESS)
            binary=root/'test'
            subprocess.run(['cc','-std=c11','-O2','-Wall','-Wextra','-Werror',
                '-I',str(root),'-I',str(MAIN),str(source),str(MAIN/'music_eq_analyzer.c'),
                str(MAIN/'protocol.c'),'-lm','-o',str(binary)],check=True)
            subprocess.run([str(binary)],check=True,timeout=5)
