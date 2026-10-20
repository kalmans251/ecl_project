"""Ensure only the initiating task's matching music command receives its token."""
from pathlib import Path
import subprocess,tempfile,unittest
from test_control_window import HEADERS
MAIN=Path(__file__).resolve().parents[1]/'main'
class ScopeTests(unittest.TestCase):
 def test_task_payload_and_queue_ownership(self):
  headers=dict(HEADERS)
  headers['freertos/FreeRTOS.h']+='\ntypedef int portMUX_TYPE;\n#define portMUX_INITIALIZER_UNLOCKED 0\n#define portENTER_CRITICAL(m) ((void)(m))\n#define portEXIT_CRITICAL(m) ((void)(m))\n'
  headers['freertos/task.h']='typedef void *TaskHandle_t;\nTaskHandle_t xTaskGetCurrentTaskHandle(void);\n'
  code=r'''
#include <assert.h>
#include "control_confirm.c"
QueueHandle_t router_queue=(void *)1;
static TaskHandle_t current=(void *)2;
static bool queue_ok=true;
static protocol_frame_t sent;
TaskHandle_t xTaskGetCurrentTaskHandle(void){return current;}
int xQueueSend(QueueHandle_t q,const void *p,TickType_t t){(void)q;(void)t;sent=*(const protocol_frame_t *)p;return queue_ok;}
int main(void){
 protocol_frame_t r={.railing_id=7,.length=7,.payload={1,2,3,4,CMD_SET,1,2}};
 protocol_frame_t f={.command=CMD_SET,.length=2,.payload={1,2}}, original=f;
 control_confirm_begin(&r);current=(void *)3;assert(control_confirm_send_music(&f,0));
 assert(sent.command==CMD_SET);current=(void *)2;f.payload[1]=3;
 assert(control_confirm_send_music(&f,0));assert(sent.command==CMD_SET);
 f=original;assert(control_confirm_send_music(&f,0));assert(control_confirm_end());
 assert(sent.command==CMD_APPLY && sent.railing_id==7 && sent.length==7);
 assert(!memcmp(sent.payload,r.payload,7));
 control_confirm_begin(&r);queue_ok=false;f=original;
 assert(!control_confirm_send_music(&f,0));assert(!control_confirm_end());
 return 0;
}
'''
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)
   for name,body in headers.items():
    f=p/name;f.parent.mkdir(parents=True,exist_ok=True);f.write_text(body)
   (p/'test.c').write_text(code)
   subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-I',str(p),'-I',str(MAIN),str(p/'test.c'),'-o',str(p/'test')],check=True)
   subprocess.run([str(p/'test')],check=True)
