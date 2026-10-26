from pathlib import Path
import subprocess,tempfile,unittest
from test_control_window import HEADERS
MAIN=Path(__file__).resolve().parents[1]/'main'
class EmergencyTests(unittest.TestCase):
 def test_real_manager_duplicate_cancel_and_call_end(self):
  code=r'''
#include <assert.h>
#include "emergency_manager.c"
QueueHandle_t router_queue=(void*)1;
static bool call,fail_queue;static unsigned restored,stops;static uint8_t confirmed;
int xQueueSend(QueueHandle_t q,const void *p,TickType_t t){(void)q;(void)t;
 const protocol_frame_t *f=p;
 if(fail_queue && f->dst==NODE_WROOM)return 0;
 if(f->dst==NODE_S3)confirmed=f->payload[0];return 1;}
void music_policy_add_pause_reason(uint32_t r){(void)r;}
void music_policy_remove_pause_reason(uint32_t r){(void)r;}
void sleep_manager_resume_after_emergency(void){++restored;}
bool call_manager_is_active(void){return call;}
call_origin_t call_manager_get_origin(void){return CALL_ORIGIN_EMERGENCY;}
bool call_manager_start(call_origin_t o){(void)o;call=true;return true;}
bool call_manager_end(void){++stops;return true;}
bool call_manager_session_matches(uint32_t s){(void)s;return false;}
bool call_manager_bind_session(uint32_t s){(void)s;return true;}
int main(void){
 emergency_manager_init();assert(emergency_manager_start(1,10));assert(confirmed==0x80);
 assert(!emergency_manager_cancel(1,11));assert(emergency_manager_is_active());
 fail_queue=true;assert(!emergency_manager_cancel(1,10));assert(emergency_manager_is_active());
 fail_queue=false;assert(emergency_manager_cancel(1,10));assert(confirmed==0x82 && restored==1);
 assert(emergency_manager_cancel(1,10));assert(restored==1);
 assert(emergency_manager_start(1,10));assert(!emergency_manager_is_active()); // delayed START cannot resurrect
 assert(emergency_manager_start(1,12));assert(emergency_manager_ack(12));assert(confirmed==0x81);
 assert(!emergency_manager_is_active() && call);
 assert(emergency_manager_cancel(1,12));assert(stops==1 && confirmed==0x81); // no premature END
 call=false;emergency_manager_call_ended();assert(confirmed==0x82 && restored==2);
 assert(emergency_manager_cancel(1,12));assert(restored==2);
 emergency_manager_init();assert(emergency_manager_cancel(1,13));assert(confirmed==0x82);
 return 0;
}
'''
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)
   for name,content in HEADERS.items():
    f=p/name;f.parent.mkdir(parents=True,exist_ok=True);f.write_text(content)
   (p/'esp_log.h').write_text('#define ESP_LOGI(...) ((void)0)\n#define ESP_LOGW(...) ((void)0)\n#define ESP_LOGE(...) ((void)0)\n')
   (p/'test.c').write_text(code)
   subprocess.run(['cc','-std=c11','-Wno-unused-variable','-I',d,'-I',str(MAIN),str(p/'test.c'),'-o',str(p/'test')],check=True)
   subprocess.run([str(p/'test')],check=True)
