"""Compile the actual capture worker and verify physical readiness ordering."""
from pathlib import Path
import subprocess, tempfile, unittest
ROOT=Path(__file__).resolve().parents[1]
HEADERS={
'Arduino.h': '''#pragma once
#include <stdint.h>
#include <stddef.h>
struct Console {template<class... T> void println(T...){} template<class... T> void printf(T...){} };extern Console Serial;
unsigned micros();unsigned millis();
''',
'freertos/queue.h': '''#pragma once
#include <stdint.h>
#include <stddef.h>
typedef void *QueueHandle_t;typedef unsigned TickType_t;typedef int portMUX_TYPE;
#define portMUX_INITIALIZER_UNLOCKED 0
#define portENTER_CRITICAL(x) ((void)(x))
#define portEXIT_CRITICAL(x) ((void)(x))
#define pdMS_TO_TICKS(x) (x)
#define pdTRUE 1
#define pdPASS 1
QueueHandle_t xQueueCreate(unsigned,unsigned);void vQueueDelete(QueueHandle_t);
int xQueueSend(QueueHandle_t,const void *,unsigned);int xQueueReceive(QueueHandle_t,void *,unsigned);
int xTaskCreate(void(*)(void*),const char*,unsigned,void*,unsigned,void*);
unsigned xTaskGetTickCount();void vTaskDelay(unsigned);
''',
'codec2.h': '''#pragma once
struct CODEC2 {};
#define CODEC2_MODE_2400 1
CODEC2 *codec2_create(int);void codec2_destroy(CODEC2*);
unsigned codec2_samples_per_frame(CODEC2*);unsigned codec2_bits_per_frame(CODEC2*);
void codec2_encode(CODEC2*,unsigned char*,short*);
''',
'driver/i2s.h': '''#pragma once
#include <stddef.h>
typedef int i2s_port_t;typedef int i2s_mode_t;typedef int esp_err_t;
#define I2S_NUM_0 0
#define I2S_MODE_MASTER 1
#define I2S_MODE_RX 2
#define I2S_BITS_PER_SAMPLE_32BIT 32
#define I2S_CHANNEL_FMT_ONLY_RIGHT 1
#define I2S_CHANNEL_FMT_ONLY_LEFT 0
#define I2S_COMM_FORMAT_STAND_I2S 0
#define I2S_PIN_NO_CHANGE -1
#define ESP_OK 0
#define ESP_ERR_TIMEOUT 1
struct i2s_config_t {int mode,sample_rate,bits_per_sample,channel_format,communication_format,intr_alloc_flags,dma_buf_count;size_t dma_buf_len;bool use_apll;};
struct i2s_pin_config_t {int mck_io_num,bck_io_num,ws_io_num,data_out_num,data_in_num;};
const char *esp_err_to_name(int);
int i2s_driver_install(int,const i2s_config_t*,int,void*);int i2s_set_pin(int,const i2s_pin_config_t*);
int i2s_driver_uninstall(int);int i2s_start(int);int i2s_stop(int);
int i2s_read(int,void*,size_t,size_t*,unsigned);
'''}
HARNESS=r'''
#include <cassert>
#include <csetjmp>
#include "microphone_codec2.cpp"
Console Serial;static std::jmp_buf done;static int scenario;static bool initialized,stopped;static unsigned destroys;
unsigned micros(){return 0;}unsigned millis(){return 0;}unsigned xTaskGetTickCount(){return 0;}
QueueHandle_t xQueueCreate(unsigned,unsigned){return (void*)1;}void vQueueDelete(QueueHandle_t){}
int xQueueSend(QueueHandle_t,const void*,unsigned){return 1;}int xQueueReceive(QueueHandle_t,void*,unsigned){return 0;}
int xTaskCreate(void(*)(void*),const char*,unsigned,void*,unsigned,void*){return pdPASS;}
void vTaskDelay(unsigned){
 if(scenario==0){assert(stopped && destroys==1 && microphone_codec2_readiness()==1);}
 else assert(microphone_codec2_readiness()==2);
 std::longjmp(done,1);
}
const char *esp_err_to_name(int){return "error";}
int i2s_driver_install(int,const i2s_config_t*,int,void*){return 0;}
int i2s_set_pin(int,const i2s_pin_config_t*){return 0;}int i2s_driver_uninstall(int){return 0;}
int i2s_stop(int){
 if(initialized){assert(microphone_codec2_readiness()==0);stopped=true;return scenario==3?2:0;}
 return 0;
}
int i2s_start(int){assert(microphone_codec2_readiness()==0);return scenario==2?2:0;}
int i2s_read(int,void*,size_t,size_t *n,unsigned timeout){
 *n=0;if(!timeout)return 0;
 assert(microphone_codec2_readiness()==1);
 microphone_codec2_set_enabled(false);
 assert(microphone_codec2_readiness()==0);
 return 0;
}
CODEC2 *codec2_create(int){static CODEC2 c;return scenario==1?nullptr:&c;}
void codec2_destroy(CODEC2*){++destroys;}
unsigned codec2_samples_per_frame(CODEC2*){return 160;}unsigned codec2_bits_per_frame(CODEC2*){return 48;}
void codec2_encode(CODEC2*,unsigned char*,short*){}
uint32_t audio_session_id(){return 1;}bool audio_session_field_tx_enabled(){return true;}
bool audio_session_send_codec2(const uint8_t*,uint8_t,uint16_t,uint32_t){return true;}
bool ble_link_is_connected(){return true;}
int main(){
 for(scenario=0;scenario<4;++scenario){
  initialized=false;stopped=false;destroys=0;
  assert(microphone_codec2_init());initialized=true;
  microphone_codec2_set_enabled(true);assert(microphone_codec2_readiness()==0);
  uint32_t old=s_generation;microphone_codec2_set_enabled(true);
  publish(old,1);assert(microphone_codec2_readiness()==0); // stale worker cannot publish ready
  if(setjmp(done)==0)capture_task(nullptr);
 }
}
'''
class MicrophoneReadinessTests(unittest.TestCase):
    def test_readiness_requires_i2s_and_encoder_and_stop_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for name,text in HEADERS.items():
                p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
            (root/'test.cpp').write_text(HARNESS)
            subprocess.run(['c++','-std=c++11','-Wall','-Wextra','-Werror','-I',str(root),
                '-I',str(ROOT/'include'),'-I',str(ROOT/'src'),str(root/'test.cpp'),'-o',str(root/'test')],check=True)
            subprocess.run([str(root/'test')],check=True,timeout=5)
