#include <stdlib.h>
#include <string.h>
#include "esp_log.h"
#include "esp_timer.h"
#include "esp_random.h"
#include "led_strip.h"
#include "led_strip_rmt.h"
#include "board_config.h"
#include "system_state.h"
#include "emergency_manager.h"
#include "led_task.h"
#include "led_eq_fresh.h"
#include "led_design.h"

_Static_assert(LED_NUM_ROWS==LED_DESIGN_ROWS && LEDS_PER_ROW==LED_DESIGN_COLS,
               "LED design requires a 4 x 31 serpentine panel");
static const char *TAG="LED_TASK";
QueueHandle_t led_command_queue=NULL;
QueueHandle_t led_eq_queue=NULL;
static led_strip_handle_t s_strip_right=NULL,s_strip_left=NULL;
static led_design_t s_design;
static led_eq_data_t s_latest_eq;
static uint32_t s_last_eq_ms;
static bool s_have_eq,s_output_currently_off=true;

static void led_output_off(void) {
    if(s_output_currently_off)return;
    ESP_ERROR_CHECK(led_strip_clear(s_strip_right));
    ESP_ERROR_CHECK(led_strip_clear(s_strip_left));
    s_output_currently_off=true;
}
static void led_show_all(void) {
    for(unsigned i=0;i<LED_NUM_PER_SIDE;i++) {
        led_rgb_t right=s_design.pixels[0][i],left=s_design.pixels[1][i];
        led_strip_set_pixel(s_strip_right,i,right.r,right.g,right.b);
        led_strip_set_pixel(s_strip_left,i,left.r,left.g,left.b);
    }
    ESP_ERROR_CHECK(led_strip_refresh(s_strip_right));
    ESP_ERROR_CHECK(led_strip_refresh(s_strip_left));
    s_output_currently_off=false;
}
static void handle_command(const led_command_t *cmd) {
    switch(cmd->type) {
        case LED_COMMAND_START:system_state_set_led_enabled(true);break;
        case LED_COMMAND_STOP:system_state_set_led_enabled(false);led_output_off();break;
        case LED_COMMAND_SET_MODE:
            system_state_set_led_mode(cmd->mode);
            system_state_set_led_pattern(cmd->mode,cmd->pattern);
            if(cmd->mode==LED_MODE_WEATHER)system_state_set_weather(cmd->weather);
            break;
        case LED_COMMAND_SET_WEATHER:system_state_set_weather(cmd->weather);break;
        default:break;
    }
}

static void init_strip(
    int gpio_num,
    led_strip_handle_t *handle
)
{
    led_strip_config_t strip_config =
    {
        .strip_gpio_num =
            gpio_num,

        .max_leds =
            LED_NUM_PER_SIDE,

        .led_model =
            LED_MODEL_WS2812,

        .color_component_format =
            LED_STRIP_COLOR_COMPONENT_FMT_GRB,

        .flags =
        {
            .invert_out =
                false,
        },
    };


    led_strip_rmt_config_t rmt_config =
    {
        .clk_src =
            RMT_CLK_SRC_DEFAULT,

        .resolution_hz =
            10 * 1000 * 1000,

        /*
         * RMT 내부 메모리
         */
        .mem_block_symbols =
            64,

        .flags =
        {
            /*
             * 좌/우 두 RMT 채널을 사용하므로
             * 우선 DMA 없이 사용
             */
            .with_dma =
                false,
        },
    };


    esp_err_t err =
        led_strip_new_rmt_device(
            &strip_config,
            &rmt_config,
            handle
        );


    if (err != ESP_OK)
    {
        ESP_LOGE(
            TAG,
            "LED init failed GPIO=%d: %s",
            gpio_num,
            esp_err_to_name(err)
        );

        return;
    }


    ESP_ERROR_CHECK(
        led_strip_clear(
            *handle
        )
    );


    ESP_LOGI(
        TAG,
        "LED strip initialized GPIO=%d",
        gpio_num
    );
}



void led_task_init(void) {
    led_command_queue=xQueueCreate(8,sizeof(led_command_t));
    led_eq_queue=xQueueCreate(1,sizeof(led_eq_data_t));
    if(!led_command_queue || !led_eq_queue)abort();
    led_design_init(&s_design,esp_random());
    init_strip(LED_DATA_PIN_RIGHT,&s_strip_right);
    init_strip(LED_DATA_PIN_LEFT,&s_strip_left);
    if(!s_strip_right || !s_strip_left)abort();
    ESP_LOGI(TAG,"LED design ready: 6 basic / 3 weather / 3 music patterns");
}
void led_task(void *arg) {
    (void)arg;
    led_command_t command;
    led_eq_data_t eq;
    while(1) {
        while(xQueueReceive(led_command_queue,&command,0)==pdTRUE)handle_command(&command);
        uint32_t now=(uint32_t)(esp_timer_get_time()/1000);
        if(xQueueReceive(led_eq_queue,&eq,0)==pdTRUE) {
            s_latest_eq=eq;s_last_eq_ms=now;s_have_eq=true;
        }
        p4_system_state_t state;system_state_get(&state);
        if(state.call_active || !state.music_playing) {
            s_latest_eq.length=0;s_have_eq=false;
        }
        if(!state.led_enabled || state.sleep_active) {
            led_output_off();
            /* Wake starts a clean frame; no pre-sleep trails/EQ are replayed. */
            s_design.initialized=false;s_have_eq=false;
            vTaskDelay(1);continue;
        }
        bool fresh=s_latest_eq.length==LED_EQ_BANDS && led_eq_is_fresh(s_have_eq,s_last_eq_ms,now);
        uint8_t pattern=state.led_mode==LED_MODE_MUSIC?state.led_music_pattern:state.led_basic_pattern;
        if(led_design_render(&s_design,now,state.led_mode,state.weather_type,pattern,
                             state.call_active || emergency_manager_is_active(),fresh,s_latest_eq.data))led_show_all();
        vTaskDelay(1);
    }
}
