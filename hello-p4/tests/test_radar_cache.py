from pathlib import Path
import subprocess,tempfile,unittest
MAIN=Path(__file__).resolve().parents[1]/'main'
class RadarCacheTests(unittest.TestCase):
 def test_actual_cache_protocol_and_expiry(self):
  code=r'''
#include <assert.h>
#include "radar_cache.c"
static int64_t now=1000000;
int64_t esp_timer_get_time(void){return now;}
int main(void){
 protocol_frame_t q={.railing_id=1,.src=NODE_PI,.dst=NODE_P4,.service=SERVICE_RADAR,.command=CMD_STATUS_REQUEST,.length=5,.payload={1,2,3,4,0}},r={0};
 assert(radar_cache_reply(&q,&r));assert(r.length==15 && !r.payload[6]);
 protocol_frame_t f={.railing_id=1,.src=NODE_S3,.dst=NODE_P4,.service=SERVICE_RADAR,.command=CMD_DATA,.length=27,.payload={1,2,1}};
 /* Slot 2 (not packed): x=-1000,y=2000,resolution=100. */
 f.payload[11]=0xfc;f.payload[12]=0x18;f.payload[13]=7;f.payload[14]=0xd0;f.payload[18]=100;
 assert(radar_cache_capture(&f));radar_cache_reply(&q,&r);
 assert(r.payload[5]==2 && r.payload[6]==1 && r.payload[7]==1 && r.length==15);
 q.payload[4]=1;radar_cache_reply(&q,&r);assert(r.length==19 && r.payload[15]==0xfc && r.payload[18]==0xd0);
 uint8_t seq=r.payload[11];
 f.payload[2]=0;memset(f.payload+3,0,24);
 radar_cache_capture(&f);radar_cache_reply(&q,&r);assert(r.payload[7]==1 && r.payload[11]==seq);
 radar_cache_capture(&f);radar_cache_reply(&q,&r);assert(r.payload[7]==1);
 radar_cache_capture(&f);radar_cache_reply(&q,&r);assert(r.payload[7]==0 && r.length==15);
 now+=1600000;radar_cache_reply(&q,&r);assert(!r.payload[6]);
 f.payload[1]=1;radar_cache_capture(&f);radar_cache_reply(&q,&r);assert(r.payload[6] && r.payload[5]==1);
 f.src=NODE_WROOM;assert(!radar_cache_capture(&f));
 q.src=NODE_S3;assert(!radar_cache_reply(&q,&r));
 return 0;
}
'''
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);(p/'esp_timer.h').write_text('#include <stdint.h>\nint64_t esp_timer_get_time(void);\n');(p/'test.c').write_text(code)
   subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-I',d,'-I',str(MAIN),str(p/'test.c'),'-o',str(p/'test')],check=True)
   subprocess.run([str(p/'test')],check=True)
