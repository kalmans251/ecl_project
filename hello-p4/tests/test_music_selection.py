"""Exercise actual P4 forwarding and policy guards for explicit track playback."""
from pathlib import Path
import subprocess
import tempfile
import unittest
MAIN = Path(__file__).resolve().parents[1] / 'main'

class SelectionTests(unittest.TestCase):
    def test_policy_and_device_confirmation(self):
        src = (MAIN / 'p4_controller.c').read_text()
        start = src.index('static void handle_music(\n    const protocol_frame_t *frame\n)\n{')
        end = src.index('    /* ========================================================\n     * WROOM -> P4 EVENT', start)
        handler = src[start:end] + '}\n'
        code = r'''
#include <assert.h>
#include <stdbool.h>
#include "protocol.h"
#define LED_MODE_MUSIC 3
#define portMAX_DELAY 0
static int router_queue;
static bool session=true, blocked, call, emergency;
typedef struct {int led_mode;bool sleep_active;} p4_system_state_t;
static p4_system_state_t state={3,false};
static protocol_frame_t sent;
static unsigned starts;
static int xQueueSend(int q,const protocol_frame_t *f,int t){(void)q;(void)t;sent=*f;return 1;}
static void system_state_get(p4_system_state_t *out){*out=state;}
static bool music_manager_is_session_enabled(void){return session;}
static bool music_policy_is_blocked(void){return blocked;}
static bool call_manager_is_active(void){return call;}
static bool emergency_manager_is_active(void){return emergency;}
static void music_manager_disable_session(void){session=false;}
static void music_policy_on_started(void){starts++;}
static void music_policy_on_stopped(void){}
static void music_policy_on_paused(void){}
static void music_policy_on_resumed(void){}
''' + handler + r'''
int main(void){
 protocol_frame_t f={0};f.src=NODE_PI;f.dst=NODE_P4;f.service=SERVICE_MUSIC;
 f.command=CMD_APPLY;f.length=12;f.payload[4]=CMD_MUSIC_PLAY;
 handle_music(&f);assert(sent.dst==NODE_WROOM && sent.command==CMD_APPLY && starts==0);
 bool *guards[]={&blocked,&call,&emergency,&state.sleep_active};
 for(unsigned i=0;i<4;i++){*guards[i]=true;handle_music(&f);
 assert(sent.dst==NODE_PI && sent.command==CMD_APPLY_RESULT && sent.payload[5]==1);*guards[i]=false;}
 session=false;handle_music(&f);assert(sent.payload[5]==1);session=true;
 state.led_mode=1;handle_music(&f);assert(sent.payload[5]==1);state.led_mode=3;
 f.src=NODE_WROOM;f.command=CMD_APPLY_RESULT;f.length=14;f.payload[5]=0;f.payload[6]=1;
 handle_music(&f);assert(sent.src==NODE_WROOM && sent.dst==NODE_PI && sent.length==14 && starts==1);
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'t.c').write_text(code)
            subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-I',str(MAIN),str(p/'t.c'),'-o',str(p/'t')],check=True)
            subprocess.run([str(p/'t')],check=True)
