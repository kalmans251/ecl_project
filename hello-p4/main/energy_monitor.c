#include "energy_monitor.h"
#include "board_config.h"
#include "sdkconfig.h"
#include "driver/i2c_master.h"
#include "driver/gpio.h"
#include "esp_log.h"
#include "esp_err.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include <string.h>
#include <stdlib.h>

static const int shunts[2]={CONFIG_RAIL_LEFT_SHUNT_MOHM,CONFIG_RAIL_RIGHT_SHUNT_MOHM};
static portMUX_TYPE mux = portMUX_INITIALIZER_UNLOCKED;
static struct { bool valid; uint16_t mv; int32_t ma; int64_t at; } cache[2];
#ifdef CONFIG_RAIL_ENERGY_ENABLED
static i2c_master_bus_handle_t bus;
static i2c_master_dev_handle_t dev[2];

static const char *TAG="ENERGY";
static esp_err_t read_reg(int n,uint8_t reg,uint16_t *value) {
    uint8_t bytes[2];
    esp_err_t err=i2c_master_transmit_receive(dev[n],&reg,1,bytes,2,30);
    if(err!=ESP_OK)return err;
    *value=((uint16_t)bytes[0]<<8)|bytes[1];return ESP_OK;
}
static const uint16_t addresses[]={INA219_ADDR_LEFT,INA219_ADDR_RIGHT};
static struct { bool seen,ok; int64_t logged_at; } diagnostics[2];
static void report(int n,bool ok,const char *stage,esp_err_t err,
                   uint16_t voltage,uint16_t shunt,unsigned read_mask) {
    int64_t now=esp_timer_get_time();
    bool transition=diagnostics[n].seen && diagnostics[n].ok!=ok;
    if(!diagnostics[n].seen || transition || (!ok && now-diagnostics[n].logged_at>=10000000)) {
        if(ok) {
            ESP_LOGI(TAG,"INA219 channel=%d addr=0x%02x ready bus_mV=%u shunt_uV=%ld raw_bus=0x%04x raw_shunt=0x%04x",
                n+1,(unsigned)addresses[n],(unsigned)(voltage>>3)*4,
                (long)(int16_t)shunt*10,(unsigned)voltage,(unsigned)shunt);
        } else {
            ESP_LOGW(TAG,"INA219 channel=%d addr=0x%02x unavailable stage=%s error=%s read_mask=%u raw_bus=0x%04x raw_shunt=0x%04x",
                n+1,(unsigned)addresses[n],stage,esp_err_to_name(err),read_mask,
                (unsigned)voltage,(unsigned)shunt);
        }
        diagnostics[n].logged_at=now;
    }
    diagnostics[n].seen=true;diagnostics[n].ok=ok;
}
static void monitor(void *unused) {
    (void)unused;
    bool configured[2]={false,false};
    for(;;) {
        for(int n=0;n<2;n++) {
            if(!dev[n])continue;
            uint16_t voltage=0,shunt=0;unsigned read_mask=0;
            esp_err_t err=ESP_OK;const char *stage="config_write";
            if(!configured[n]) {
                /* 32V range, +/-320mV shunt, 12-bit bus/shunt, continuous. */
                const uint8_t config[]={0,0x39,0x9f};
                err=i2c_master_transmit(dev[n],config,sizeof config,30);
                configured[n]=err==ESP_OK;
                if(configured[n])vTaskDelay(pdMS_TO_TICKS(5));
            }
            if(err==ESP_OK){stage="bus_read";err=read_reg(n,2,&voltage);if(err==ESP_OK)read_mask|=1;}
            if(err==ESP_OK){stage="shunt_read";err=read_reg(n,1,&shunt);if(err==ESP_OK)read_mask|=2;}
            bool ok=err==ESP_OK;
            if(ok) {
                if(!(voltage&2)){stage="conversion_not_ready";ok=false;}
                else if(voltage&1){stage="overflow";ok=false;}
                else if((voltage>>3)>6500){stage="bus_out_of_range";ok=false;}
                else if(abs((int16_t)shunt)>=32000){stage="shunt_saturated";ok=false;}
            }
            uint16_t mv=(voltage>>3)*4;
            int32_t ma=shunts[n]?((int32_t)(int16_t)shunt*10)/shunts[n]:0;
            portENTER_CRITICAL(&mux);
            bool was=cache[n].valid;
            if(ok) {
                cache[n].mv=was?(cache[n].mv*7u+mv)/8u:mv;
                cache[n].ma=ma;cache[n].at=esp_timer_get_time();
            }
            cache[n].valid=ok;
            portEXIT_CRITICAL(&mux);
            report(n,ok,stage,err,voltage,shunt,read_mask);
            if(!ok)configured[n]=false;
        }
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}
#endif
static void put16(uint8_t *p,uint16_t v){p[0]=v>>8;p[1]=v;}
static void put32(uint8_t *p,int32_t v){uint32_t u=(uint32_t)v;p[0]=u>>24;p[1]=u>>16;p[2]=u>>8;p[3]=u;}
void energy_monitor_encode(uint8_t out[ENERGY_WIRE_SIZE]) {
    memset(out,0,ENERGY_WIRE_SIZE);
    int64_t now=esp_timer_get_time();
    portENTER_CRITICAL(&mux);
    for(int n=0;n<2;n++)if(cache[n].valid && now-cache[n].at<=3000000) {
        out[0]|=1u<<n;put16(out+3+n*2,cache[n].mv);
        if(shunts[n]>0){out[0]|=1u<<(n+2);put32(out+7+n*4,cache[n].ma);}
        if(CONFIG_RAIL_BATTERY_CHANNEL==n+1 && cache[n].mv>=8000 && cache[n].mv<=16000) {
            out[0]|=16;put16(out+1,cache[n].mv);
        }
    }
    portEXIT_CRITICAL(&mux);
}
void energy_monitor_init(void) {
#ifndef CONFIG_RAIL_ENERGY_ENABLED
    ESP_LOGW("ENERGY","INA219 sampling disabled in menuconfig");
    return;
#else
    i2c_master_bus_config_t cfg={.i2c_port=I2C_NUM_0,.sda_io_num=I2C_SDA_PIN,
        .scl_io_num=I2C_SCL_PIN,.clk_source=I2C_CLK_SRC_DEFAULT,.glitch_ignore_cnt=7,
        .flags.enable_internal_pullup=true};
    esp_err_t err=i2c_new_master_bus(&cfg,&bus);
    if(err!=ESP_OK){ESP_LOGW(TAG,"I2C init failed SDA=%d SCL=%d error=%s",I2C_SDA_PIN,I2C_SCL_PIN,esp_err_to_name(err));return;}
    ESP_LOGI(TAG,"I2C SDA=%d SCL=%d speed=100000Hz; sensors 0x40/0x41",I2C_SDA_PIN,I2C_SCL_PIN);
    for(int n=0;n<2;n++) {
        i2c_device_config_t d={.dev_addr_length=I2C_ADDR_BIT_LEN_7,.device_address=addresses[n],.scl_speed_hz=100000};
        err=i2c_master_bus_add_device(bus,&d,&dev[n]);
        if(err!=ESP_OK){dev[n]=NULL;ESP_LOGW(TAG,"INA219 channel=%d addr=0x%02x registration failed error=%s",n+1,(unsigned)addresses[n],esp_err_to_name(err));}
    }
    if(xTaskCreate(monitor,"energy",3072,NULL,3,NULL)!=pdPASS)ESP_LOGW(TAG,"Energy task allocation failed");
    ESP_LOGI(TAG,"Battery channel=%d; shunts=%d/%d mOhm (0=unknown)",CONFIG_RAIL_BATTERY_CHANNEL,shunts[0],shunts[1]);
#endif
}
