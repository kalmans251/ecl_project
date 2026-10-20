from pathlib import Path
import subprocess,tempfile,unittest
from test_control_window import HEADERS
MAIN=Path(__file__).resolve().parents[1]/'main'
class OutboxTests(unittest.TestCase):
 def test_retention_ack_duplicate_and_overflow(self):
  headers=dict(HEADERS)
  headers['freertos/FreeRTOS.h']+='\ntypedef int portMUX_TYPE;\n#define portMUX_INITIALIZER_UNLOCKED 0\n#define portENTER_CRITICAL(m) ((void)(m))\n#define portEXIT_CRITICAL(m) ((void)(m))\n'
  headers['esp_random.h']='#include <stdint.h>\nstatic inline uint32_t esp_random(void){return 1234;}\n'
  headers['esp_log.h']+='\n#define ESP_LOGE(...) ((void)0)\n'
  code=r'''
#include <assert.h>
#include "event_outbox.c"
int main(void){
 protocol_frame_t f={.railing_id=1,.src=NODE_P4,.dst=NODE_PI,
    .service=SERVICE_EMERGENCY,.command=CMD_START,.length=5,.payload={1,0,0,0,4}};
 protocol_frame_t poll={.railing_id=1,.length=8,.payload={8,7,6,5}}, reply;
 assert(event_outbox_capture(&f));f.command=CMD_STOP;assert(event_outbox_capture(&f));
 event_outbox_reply(&poll,&reply);assert(count==2 && reply.payload[13]==CMD_START);
 uint32_t first=get32(reply.payload+4);assert(first);
 event_outbox_reply(&poll,&reply);assert(count==2 && get32(reply.payload+4)==first);
 put32(poll.payload+4,first+20);event_outbox_reply(&poll,&reply);assert(count==2);
 put32(poll.payload+4,first);event_outbox_reply(&poll,&reply);
 assert(count==1 && reply.payload[13]==CMD_STOP && !memcmp(reply.payload,poll.payload,4));
 uint32_t second=get32(reply.payload+4);
 event_outbox_reply(&poll,&reply);assert(count==1); // repeated ACK cannot pop the next event
 put32(poll.payload+4,second);event_outbox_reply(&poll,&reply);assert(count==0 && reply.length==14);
 assert(get32(reply.payload+4)==0);
 for(unsigned i=0;i<CAPACITY+1;i++)assert(event_outbox_capture(&f));
 assert(count==CAPACITY && dropped==1);
 memset(poll.payload+4,0,4);event_outbox_reply(&poll,&reply);assert(get32(reply.payload+8)==1);
 f.command=CMD_DATA;assert(!event_outbox_capture(&f)); // requested ACKED response stays direct
 protocol_frame_t end={.railing_id=1,.src=NODE_P4,.dst=NODE_PI,.service=SERVICE_AUDIO,
    .command=CMD_DATA,.length=8,.payload={AUDIO_DATA_EVENT,AUDIO_EVENT_CALL_ENDED,0,0,1,2,3,4}};
 event_outbox_store_call_end(&end);event_outbox_reply(&poll,&reply);
 assert(reply.length==22 && reply.payload[12]==SERVICE_AUDIO && count==CAPACITY);
 assert(get32(reply.payload+18)==0x01020304);
 uint32_t terminal_token=get32(reply.payload+4);
 event_outbox_store_call_end(&end);event_outbox_reply(&poll,&reply);
 assert(get32(reply.payload+4)==terminal_token); // duplicate STOP shares terminal report
 event_outbox_clear_call_end();event_outbox_reply(&poll,&reply);
 assert(reply.length==19 && reply.payload[12]==SERVICE_EMERGENCY); // new call removes old END
 event_outbox_store_call_end(&end);put32(poll.payload+4,terminal_id);
 event_outbox_reply(&poll,&reply);assert(terminal_id==0 && count==CAPACITY);
 return 0;
}
'''
  with tempfile.TemporaryDirectory() as d:
   root=Path(d)
   for name,body in headers.items():
    p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(body)
   (root/'test.c').write_text(code)
   subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-I',str(root),'-I',str(MAIN),str(root/'test.c'),'-o',str(root/'test')],check=True)
   subprocess.run([str(root/'test')],check=True)
