"""Compile the actual APPLY dispatcher; model hardware/policy side effects."""
from pathlib import Path
import subprocess,tempfile,unittest
MAIN=Path(__file__).resolve().parents[1]/'main'
class ConfirmTests(unittest.TestCase):
 def test_dispatch_and_truthful_outcomes(self):
  source=(MAIN/'p4_controller.c').read_text()
  handler=source[source.index('static void handle_general_apply('):source.index('\nvoid p4_controller_task(')]
  harness=r'''
#include <assert.h>
#include <stdbool.h>
#include <string.h>
#include "protocol.h"
#include "system_state.h"
#include "detection_manager.h"
static const protocol_frame_t *s_apply_request;
static bool s_apply_accepted,active,emergency,queue_ok=true,manager_ok=true;
static unsigned replies,led_calls,actions;
static uint8_t result[11];
static p4_system_state_t state;
static bool call_manager_is_active(void){return active;}
static bool emergency_manager_is_active(void){return emergency;}
void system_state_get(p4_system_state_t *out){*out=state;}
static void send_response(const protocol_frame_t *f,uint8_t service,uint8_t cmd,const uint8_t *p,uint8_t n){
 assert(f->service==service && cmd==CMD_APPLY_RESULT && n==7);memcpy(result,p,n);replies++;
}
static void handle_led(const protocol_frame_t *f){(void)f;assert(s_apply_request);led_calls++;s_apply_accepted=queue_ok;}
static void handle_power(const protocol_frame_t *f){actions++;if(f->command==CMD_SET)state.power_mode=f->payload[0];}
static bool power_control_get_ac(void){return true;}
static bool power_control_get_battery(void){return false;}
static void handle_projector(const protocol_frame_t *f){actions++;state.projector_enabled=f->command==CMD_START;}
static bool projector_control_get(void){return state.projector_enabled;}
static void handle_sleep(const protocol_frame_t *f){actions++;state.sleep_mode_enabled=f->command==CMD_START;}
static void handle_detection(const protocol_frame_t *f){(void)f;actions++;s_apply_accepted=manager_ok;}
detection_source_t detection_manager_get_source(void){return DETECTION_SOURCE_CCTV;}
static void control_confirm_begin(const protocol_frame_t *f){(void)f;}
static bool control_confirm_end(void){return false;}
static bool music_manager_start(void){actions++;return manager_ok;}
static bool music_manager_next(void){actions++;return manager_ok;}
static void music_manager_user_pause(void){actions++;}
static void music_manager_user_resume(void){actions++;}
static bool music_manager_set_mode(music_play_mode_t m){(void)m;actions++;return manager_ok;}
''' + handler + r'''
static protocol_frame_t req(uint8_t service,uint8_t op){
 protocol_frame_t f={0};f.src=NODE_PI;f.dst=NODE_P4;f.railing_id=1;f.service=service;
 f.command=CMD_APPLY;f.length=5;f.payload[0]=42;f.payload[4]=op;return f;
}
int main(void){
 protocol_frame_t f=req(SERVICE_PROJECTOR,CMD_START);handle_general_apply(&f);
 assert(result[0]==42 && result[4]==CMD_START && result[5]==0 && state.projector_enabled);
 active=true;unsigned n=actions;handle_general_apply(&f);assert(result[5]==1 && actions==n);active=false;
 f=req(SERVICE_SYSTEM,CMD_PING);handle_general_apply(&f);assert(result[5]==0 && result[6]==1);
 f.length=6;handle_general_apply(&f);assert(result[5]==1);
 f=req(SERVICE_LED,CMD_START);n=replies;handle_general_apply(&f);
 assert(led_calls==1 && replies==n && !s_apply_request); /* task, not controller, owns ACK */
 queue_ok=false;handle_general_apply(&f);assert(result[5]==2);
 f=req(SERVICE_MUSIC,CMD_START);handle_general_apply(&f);assert(result[5]==3);
 manager_ok=false;handle_general_apply(&f);assert(result[5]==2);
 f=req(SERVICE_DETECTION,CMD_DATA);f.length=10;f.payload[5]=DETECT_EVENT_CCTV_NEW_PERSON;
 handle_general_apply(&f);assert(result[5]==1);
 manager_ok=true;handle_general_apply(&f);assert(result[5]==0);
 f=req(SERVICE_SLEEP,CMD_START);handle_general_apply(&f);assert(result[5]==0 && state.sleep_mode_enabled);
 f=req(SERVICE_POWER,CMD_START);state.power_mode=POWER_MODE_AUTO;handle_general_apply(&f);assert(result[5]==1);
 f=req(SERVICE_POWER,CMD_SET);f.length=6;f.payload[5]=POWER_MODE_AC;handle_general_apply(&f);assert(result[5]==0);
 f=req(SERVICE_POWER,CMD_START);handle_general_apply(&f);assert(result[5]==0);
 f=req(SERVICE_POWER,CMD_STOP);handle_general_apply(&f);assert(result[5]==2); /* stuck GPIO */
 return 0;
}
'''
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);(p/'test.c').write_text(harness)
   subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-I',str(MAIN),str(p/'test.c'),'-o',str(p/'test')],check=True)
   subprocess.run([str(p/'test')],check=True)
