"""Compile actual audio_output.c and model the driver's TX auto-clear contract."""
from pathlib import Path
import subprocess
import tempfile
import unittest

MAIN = Path(__file__).resolve().parents[1] / 'main'
HEADERS = {
'driver/uart.h': '#pragma once\n',
'driver/spi_master.h': '#pragma once\n',
'esp_err.h': '#pragma once\ntypedef int esp_err_t;\n#define ESP_OK 0\n',
'esp_log.h': '#define ESP_LOGI(tag, ...) ((void)(tag))\n',
'freertos/FreeRTOS.h': '''#pragma once
#include <stdint.h>
typedef int portMUX_TYPE;
typedef void *TaskHandle_t;
#define portMUX_INITIALIZER_UNLOCKED 0
#define portENTER_CRITICAL(x) ((void)(x))
#define portEXIT_CRITICAL(x) ((void)(x))
#define portMAX_DELAY 0xffffffff
''',
'freertos/task.h': '''#pragma once
#include "FreeRTOS.h"
TaskHandle_t xTaskGetCurrentTaskHandle(void);
''',
'driver/i2s_std.h': '''#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "esp_err.h"
typedef void *i2s_chan_handle_t;
typedef struct { bool auto_clear_after_cb; } i2s_chan_config_t;
typedef struct { uint32_t sample_rate_hz; } i2s_std_clk_config_t;
typedef struct {
 i2s_std_clk_config_t clk_cfg;
 int slot_cfg;
 struct { int mclk,bclk,ws,dout,din;
  struct { bool mclk_inv,bclk_inv,ws_inv; } invert_flags; } gpio_cfg;
} i2s_std_config_t;
#define I2S_NUM_0 0
#define I2S_ROLE_MASTER 0
#define I2S_GPIO_UNUSED -1
#define I2S_DATA_BIT_WIDTH_16BIT 16
#define I2S_SLOT_MODE_STEREO 2
#define I2S_CHANNEL_DEFAULT_CONFIG(a,b) ((i2s_chan_config_t){false})
#define I2S_STD_CLK_DEFAULT_CONFIG(rate) ((i2s_std_clk_config_t){rate})
#define I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(a,b) 0
esp_err_t i2s_new_channel(const i2s_chan_config_t *,i2s_chan_handle_t *,void *);
esp_err_t i2s_channel_init_std_mode(i2s_chan_handle_t,const i2s_std_config_t *);
esp_err_t i2s_del_channel(i2s_chan_handle_t);
esp_err_t i2s_channel_enable(i2s_chan_handle_t);
esp_err_t i2s_channel_disable(i2s_chan_handle_t);
esp_err_t i2s_channel_reconfig_std_clock(i2s_chan_handle_t,const i2s_std_clk_config_t *);
esp_err_t i2s_channel_write(i2s_chan_handle_t,const void *,size_t,size_t *,uint32_t);
''',
}
HARNESS = r'''
#include <assert.h>
#include <string.h>
#include "audio_output.c"
static bool auto_clear;
static int16_t dma[16];
static size_t dma_bytes;
static uint32_t output_rate;
TaskHandle_t xTaskGetCurrentTaskHandle(void) { return (void *)1; }
esp_err_t i2s_new_channel(const i2s_chan_config_t *cfg,i2s_chan_handle_t *tx,void *rx) {
 (void)rx; auto_clear=cfg->auto_clear_after_cb; *tx=(void *)1; return ESP_OK;
}
esp_err_t i2s_channel_init_std_mode(i2s_chan_handle_t h,const i2s_std_config_t *cfg) {
 (void)h; output_rate=cfg->clk_cfg.sample_rate_hz; return ESP_OK;
}
esp_err_t i2s_del_channel(i2s_chan_handle_t h) { (void)h; return ESP_OK; }
esp_err_t i2s_channel_enable(i2s_chan_handle_t h) { (void)h; return ESP_OK; }
esp_err_t i2s_channel_disable(i2s_chan_handle_t h) { (void)h; return ESP_OK; }
esp_err_t i2s_channel_reconfig_std_clock(i2s_chan_handle_t h,const i2s_std_clk_config_t *cfg) {
 (void)h; output_rate=cfg->sample_rate_hz; return ESP_OK;
}
esp_err_t i2s_channel_write(i2s_chan_handle_t h,const void *p,size_t n,size_t *written,uint32_t timeout) {
 (void)h; (void)timeout; assert(n<=sizeof(dma)); memcpy(dma,p,n); dma_bytes=n; *written=n; return ESP_OK;
}
/* Model completion of a TX descriptor: the IDF flag clears its old bytes. */
static int16_t tx_cycle(void) {
 int16_t sample=dma[0]; if(auto_clear) memset(dma,0,dma_bytes); return sample;
}
int main(void) {
 int16_t music[4]={12000,-12000,3000,-3000};
 assert(audio_output_init(44100));
 audio_output_set_volume(100);
 assert(audio_output_write(music,4));
 assert(tx_cycle()==12000);
 /* Paused music supplies no further PCM. Old audio must not loop. */
 for(int i=0;i<100;++i) assert(tx_cycle()==0);
 /* Resume writes real PCM at the existing rate. */
 assert(audio_output_write(music,4));
 assert(tx_cycle()==12000); assert(output_rate==44100);
 audio_output_set_volume(0);
 assert(audio_output_write(music,4)); assert(tx_cycle()==0);
 assert(audio_output_set_sample_rate(16000));
 audio_output_set_volume(10);
 assert(audio_output_write(music,4)); assert(tx_cycle()==1200);
 assert(tx_cycle()==0); assert(output_rate==16000);
 audio_output_deinit();
 assert(audio_output_init(48000));
 assert(auto_clear); assert(output_rate==48000);
 return 0;
}
'''
class AudioOutputTests(unittest.TestCase):
    def test_pause_underrun_silence_resume_gain_and_reinitialization(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for name, text in HEADERS.items():
                p=root/name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(text)
            source=root/'test.c'; source.write_text(HARNESS)
            binary=root/'test'
            subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-I',str(root),
                            '-I',str(MAIN),str(source),'-o',str(binary)],check=True)
            subprocess.run([str(binary)],check=True,timeout=5)
