"""Actual sensor code against host I2C/time models; no hardware accuracy claim."""
from pathlib import Path
import subprocess,tempfile,unittest
from test_control_window import HEADERS
MAIN=Path(__file__).resolve().parents[1]/'main'
class EnergyMonitorTests(unittest.TestCase):
 def test_measure_fault_recovery_staleness_and_signed_current(self):
  headers=dict(HEADERS)
  headers['sdkconfig.h']='#define CONFIG_RAIL_ENERGY_ENABLED 1\n#define CONFIG_RAIL_BATTERY_CHANNEL 1\n#define CONFIG_RAIL_LEFT_SHUNT_MOHM 100\n#define CONFIG_RAIL_RIGHT_SHUNT_MOHM 0\n'
  headers['driver/gpio.h']='#define GPIO_NUM_8 8\n#define GPIO_NUM_9 9\n'
  headers['esp_log.h']='#define ESP_LOGI(t,...) ((void)(t))\n#define ESP_LOGW(t,...) ((void)(t))\n'
  headers['freertos/FreeRTOS.h']+='\n#include <stdbool.h>\ntypedef int portMUX_TYPE;\n#define portMUX_INITIALIZER_UNLOCKED 0\n#define portENTER_CRITICAL(m) ((void)(m))\n#define portEXIT_CRITICAL(m) ((void)(m))\n#define pdPASS 1\n'
  headers['freertos/task.h']='void vTaskDelay(unsigned);\nint xTaskCreate(void(*fn)(void*),const char*,int,void*,int,void*);\n'
  headers['driver/i2c_master.h']='''#include <stddef.h>
#include <stdint.h>
#include <stdbool.h>
typedef void *i2c_master_bus_handle_t;
typedef void *i2c_master_dev_handle_t;
#define ESP_OK 0
#define I2C_NUM_0 0
#define I2C_CLK_SRC_DEFAULT 0
#define I2C_ADDR_BIT_LEN_7 0
typedef struct {int i2c_port,sda_io_num,scl_io_num,clk_source,glitch_ignore_cnt;struct{bool enable_internal_pullup;}flags;} i2c_master_bus_config_t;
typedef struct {int dev_addr_length,device_address,scl_speed_hz;} i2c_device_config_t;
int i2c_new_master_bus(const i2c_master_bus_config_t*,void**);
int i2c_master_bus_add_device(void*,const i2c_device_config_t*,void**);
int i2c_master_transmit(void*,const uint8_t*,size_t,int);
int i2c_master_transmit_receive(void*,const uint8_t*,size_t,uint8_t*,size_t,int);
'''
  code=r'''
#include <assert.h>
#include <setjmp.h>
#include "energy_monitor.c"
static jmp_buf end;
static int64_t now=1000000;
static bool fail=false;
static uint16_t voltage=(3300<<3)|2,shunt=5000;
int64_t esp_timer_get_time(void){return now;}
void vTaskDelay(unsigned ms){if(ms==1000)longjmp(end,1);}
int xTaskCreate(void(*fn)(void*),const char*n,int s,void*p,int pr,void*h){(void)fn;(void)n;(void)s;(void)p;(void)pr;(void)h;return 1;}
int i2c_new_master_bus(const i2c_master_bus_config_t*c,void**o){(void)c;*o=(void*)1;return 0;}
int i2c_master_bus_add_device(void*b,const i2c_device_config_t*c,void**o){(void)b;*o=(void*)(uintptr_t)c->device_address;return 0;}
int i2c_master_transmit(void*d,const uint8_t*p,size_t n,int t){(void)d;assert(n==3 && p[1]==0x39 && p[2]==0x9f && t==30);return fail?-1:0;}
int i2c_master_transmit_receive(void*d,const uint8_t*r,size_t n,uint8_t*p,size_t len,int t){(void)d;assert(n==1 && len==2 && t==30);if(fail)return -1;uint16_t v=*r==2?voltage:shunt;p[0]=v>>8;p[1]=v;return 0;}
static void step(void){if(!setjmp(end))monitor(NULL);}
int main(void){
 uint8_t out[15];energy_monitor_init();energy_monitor_encode(out);assert(out[0]==0);
 step();energy_monitor_encode(out);assert(out[0]==23); /* both V, only left A, battery */
 assert(out[1]==0x33 && out[2]==0x90);assert(out[9]==1 && out[10]==244); /* 13.2V, 500mA */
 shunt=(uint16_t)-1000;step();energy_monitor_encode(out);assert(out[7]==255 && out[10]==156); /* -100mA */
 now+=3000001;energy_monitor_encode(out);assert(out[0]==0);
 fail=true;step();energy_monitor_encode(out);assert(out[0]==0);
 fail=false;voltage=(3000<<3)|2;step();energy_monitor_encode(out);assert(out[1]==0x2e && out[2]==0xe0); /* recovery resets average:12V */
 voltage|=1;step();energy_monitor_encode(out);assert(out[0]==0); /* overflow */
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
