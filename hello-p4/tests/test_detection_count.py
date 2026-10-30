from pathlib import Path
import subprocess,tempfile,unittest
from test_control_window import HEADERS
MAIN=Path(__file__).resolve().parents[1]/'main'
class CountTests(unittest.TestCase):
 def test_reset_preserves_modes_age_and_dedup(self):
  headers=dict(HEADERS)
  headers['freertos/semphr.h']='#include <stdlib.h>\n#include "FreeRTOS.h"\ntypedef void *SemaphoreHandle_t;\nSemaphoreHandle_t xSemaphoreCreateMutex(void);\nint xSemaphoreTake(SemaphoreHandle_t,unsigned);\nint xSemaphoreGive(SemaphoreHandle_t);\n'
  headers['esp_log.h']='#include <stdio.h>\n#define ESP_LOGI(tag,...) do{(void)(tag);if(0)printf(__VA_ARGS__);}while(0)\n#define ESP_LOGW ESP_LOGI\n#define ESP_LOGE ESP_LOGI\n'
  code=r'''
#include <assert.h>
#include "detection_manager.c"
int64_t esp_timer_get_time(void){return 1000000;}
SemaphoreHandle_t xSemaphoreCreateMutex(void){return (void*)1;}
int xSemaphoreTake(SemaphoreHandle_t s,unsigned t){(void)s;(void)t;return 1;}
int xSemaphoreGive(SemaphoreHandle_t s){(void)s;return 1;}
int main(void){
 detection_summary_t s;
 detection_manager_init();
 assert(detection_manager_get_source()==DETECTION_SOURCE_CCTV);
 assert(!detection_manager_radar_new_person(99));
 detection_manager_set_source(DETECTION_SOURCE_RADAR);
 assert(detection_manager_radar_new_person(1));
 assert(!detection_manager_cctv_new_person(2));
 detection_manager_set_source(DETECTION_SOURCE_CCTV);
 assert(!detection_manager_radar_new_person(2));
 assert(detection_manager_cctv_new_person(10));
 assert(detection_manager_cctv_age_result(10,AGE_GROUP_20S));
 assert(detection_manager_cctv_new_person(11));
 detection_manager_get_summary(&s);assert(s.total_detected_count==3);
 int64_t activity=s.last_detection_ms;
 detection_manager_reset_count(&s);
 assert(s.total_detected_count==0 && s.source==DETECTION_SOURCE_CCTV);
 assert(s.age_20_count==1 && s.latest_age_group==AGE_GROUP_20S && s.last_detection_ms==activity);
 assert(!detection_manager_cctv_new_person(10));
 assert(!detection_manager_cctv_new_person(11));
 assert(detection_manager_cctv_age_result(11,AGE_GROUP_30S));
 assert(detection_manager_cctv_new_person(12));
 detection_manager_get_summary(&s);assert(s.total_detected_count==1);
 detection_manager_set_source(DETECTION_SOURCE_RADAR);
 assert(!detection_manager_radar_new_person(1));
 assert(detection_manager_radar_new_person(2));
 detection_manager_get_summary(&s);assert(s.total_detected_count==2);
 return 0;
}
'''
  with tempfile.TemporaryDirectory() as d:
   root=Path(d)
   for name,body in headers.items():
    f=root/name;f.parent.mkdir(parents=True,exist_ok=True);f.write_text(body)
   (root/'test.c').write_text(code)
   subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-I',d,'-I',str(MAIN),str(root/'test.c'),'-o',str(root/'test')],check=True)
   subprocess.run([str(root/'test')],check=True)
