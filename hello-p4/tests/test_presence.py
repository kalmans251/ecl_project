"""Exercise actual presence renewal and the existing idle timeout predicate."""
from pathlib import Path
import subprocess,tempfile,unittest
MAIN=Path(__file__).resolve().parents[1]/'main'
class PresenceTests(unittest.TestCase):
 def test_presence_renews_without_counting_and_expires_after_last_seen(self):
  source=(MAIN/'detection_manager.c').read_text()
  touch=source[source.index('bool detection_manager_touch_presence('):]
  sleep=(MAIN/'sleep_manager.c').read_text()
  start=sleep.index('static bool idle_timeout_expired')
  end=sleep.index('/* ============================================================\n * LOCK',start)
  idle=sleep[start:end]
  code='''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
typedef int detection_source_t;
typedef struct {int source;uint32_t total_detected_count;int64_t last_detection_ms;} detection_summary_t;
static detection_summary_t s_summary={1,7,0};
static int64_t clock_ms,s_enabled_since_ms;
#define SLEEP_IDLE_TIMEOUT_MS 10000
static void lock_manager(void){}
static void unlock_manager(void){}
static int64_t get_now_ms(void){return clock_ms;}
static int64_t now_ms(void){return clock_ms;}
static void detection_manager_get_summary(detection_summary_t *out){*out=s_summary;}
'''+touch+idle+'''
int main(void){
 for(clock_ms=2000;clock_ms<=30000;clock_ms+=2000){
  assert(detection_manager_touch_presence(1));
  assert(s_summary.total_detected_count==7);
  assert(!idle_timeout_expired());
 }
 clock_ms=39999;assert(!idle_timeout_expired());
 clock_ms=40000;assert(idle_timeout_expired());
 assert(!detection_manager_touch_presence(0));
 assert(s_summary.last_detection_ms==30000);
 s_summary.source=0;assert(detection_manager_touch_presence(0));
 assert(s_summary.total_detected_count==7);
}
'''
  with tempfile.TemporaryDirectory() as folder:
   p=Path(folder);(p/'test.c').write_text(code)
   subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',str(p/'test.c'),'-o',str(p/'test')],check=True)
   subprocess.run([str(p/'test')],check=True)
