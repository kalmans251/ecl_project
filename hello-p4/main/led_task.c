#include <string.h>

#include "esp_log.h"
#include "esp_timer.h"

#include "led_strip.h"
#include "led_strip_rmt.h"

#include "board_config.h"
#include "system_state.h"
#include "led_task.h"
#include "led_eq_fresh.h"


static const char *TAG =
    "LED_TASK";


/* ============================================================
 * QUEUES
 * ============================================================ */

QueueHandle_t
    led_command_queue =
        NULL;

QueueHandle_t
    led_eq_queue =
        NULL;


/* ============================================================
 * LED HANDLES
 * ============================================================ */

static led_strip_handle_t
    s_strip_right =
        NULL;

static led_strip_handle_t
    s_strip_left =
        NULL;


/* ============================================================
 * FRAME BUFFER
 *
 * 내부적으로 RGB 형태로 관리.
 * led_strip driver가 WS2812 GRB 순서를 처리.
 * ============================================================ */

typedef struct
{
    uint8_t r;

    uint8_t g;

    uint8_t b;

} rgb_t;


static rgb_t
    s_right_leds[
        LED_NUM_PER_SIDE
    ];


static rgb_t
    s_left_leds[
        LED_NUM_PER_SIDE
    ];


/* ============================================================
 * ANIMATION STATE
 * ============================================================ */

static uint32_t
    s_anim_frame =
        0;


static uint32_t
    s_last_basic_update =
        0;


static uint32_t
    s_last_weather_update =
        0;


static uint32_t
    s_last_music_update =
        0;


static bool
    s_output_currently_off =
        true;


/* ============================================================
 * LATEST EQ
 * ============================================================ */

static led_eq_data_t
    s_latest_eq;
static uint32_t s_last_eq_ms;
static bool s_have_eq;


/* ============================================================
 * XY -> INDEX
 *
 * 4 x 31 serpentine
 *
 * row 0 :  0 -> 30
 * row 1 : 61 -> 31
 * row 2 : 62 -> 92
 * row 3 :123 -> 93
 * ============================================================ */

static uint16_t led_xy_to_index(
    uint8_t row,
    uint8_t col
)
{
    if (
        row >= LED_NUM_ROWS ||
        col >= LEDS_PER_ROW
    )
    {
        return UINT16_MAX;
    }


    if (
        (row & 1) == 0
    )
    {
        return
            (
                row *
                LEDS_PER_ROW
            )
            +
            col;
    }


    return
        (
            row *
            LEDS_PER_ROW
        )
        +
        (
            LEDS_PER_ROW -
            1 -
            col
        );
}


/* ============================================================
 * PIXEL
 * ============================================================ */

static void set_pixel_right(
    uint8_t row,
    uint8_t col,

    uint8_t r,
    uint8_t g,
    uint8_t b
)
{
    uint16_t index =
        led_xy_to_index(
            row,
            col
        );


    if (
        index ==
        UINT16_MAX
    )
    {
        return;
    }


    s_right_leds[index].r =
        r;

    s_right_leds[index].g =
        g;

    s_right_leds[index].b =
        b;
}


static void set_pixel_left(
    uint8_t row,
    uint8_t col,

    uint8_t r,
    uint8_t g,
    uint8_t b
)
{
    uint16_t index =
        led_xy_to_index(
            row,
            col
        );


    if (
        index ==
        UINT16_MAX
    )
    {
        return;
    }


    s_left_leds[index].r =
        r;

    s_left_leds[index].g =
        g;

    s_left_leds[index].b =
        b;
}


/* ============================================================
 * CLEAR FRAMEBUFFER
 * ============================================================ */

static void clear_all_leds(void)
{
    memset(
        s_right_leds,
        0,
        sizeof(
            s_right_leds
        )
    );


    memset(
        s_left_leds,
        0,
        sizeof(
            s_left_leds
        )
    );
}


/* ============================================================
 * SHOW
 * ============================================================ */

static void led_show_all(void)
{
    for (
        uint16_t i = 0;
        i < LED_NUM_PER_SIDE;
        i++
    )
    {
        led_strip_set_pixel(
            s_strip_right,
            i,

            s_right_leds[i].r,
            s_right_leds[i].g,
            s_right_leds[i].b
        );


        led_strip_set_pixel(
            s_strip_left,
            i,

            s_left_leds[i].r,
            s_left_leds[i].g,
            s_left_leds[i].b
        );
    }


    led_strip_refresh(
        s_strip_right
    );


    led_strip_refresh(
        s_strip_left
    );


    s_output_currently_off =
        false;
}


/* ============================================================
 * PHYSICAL OFF
 *
 * 상태값은 건드리지 않는다.
 * 실제 LED만 OFF.
 *
 * Sleep에서 사용.
 * ============================================================ */

static void led_output_off(void)
{
    if (
        s_output_currently_off
    )
    {
        return;
    }


    led_strip_clear(
        s_strip_right
    );


    led_strip_clear(
        s_strip_left
    );


    s_output_currently_off =
        true;
}


/* ============================================================
 * BASIC MODE
 *
 * 사용자가 예시로 준 기존 animation을 기반으로 작성.
 * ============================================================ */

static bool effect_basic(
    uint32_t now_ms
)
{
    if (
        now_ms -
        s_last_basic_update
        <
        30
    )
    {
        return false;
    }


    s_last_basic_update =
        now_ms;


    clear_all_leds();


    uint8_t step =
        s_anim_frame %
        16;


    for (
        uint8_t row = 0;
        row < LED_NUM_ROWS;
        row++
    )
    {
        uint8_t g_val;


        if (
            step * 10 <
            150
        )
        {
            g_val =
                150 -
                step * 10;
        }
        else
        {
            g_val =
                0;
        }


        uint8_t left_col =
            15 -
            step;


        uint8_t right_col =
            15 +
            step;


        /*
         * 우측 난간
         */
        if (
            left_col <
            LEDS_PER_ROW
        )
        {
            set_pixel_right(
                row,
                left_col,

                0,
                255,
                g_val
            );
        }


        if (
            right_col <
            LEDS_PER_ROW
        )
        {
            set_pixel_right(
                row,
                right_col,

                0,
                255,
                g_val
            );
        }


        /*
         * 좌측 난간
         *
         * 기존 예시의 pixel2 색감을 유지
         */
        if (
            left_col <
            LEDS_PER_ROW
        )
        {
            set_pixel_left(
                row,
                left_col,

                0,
                g_val,
                255
            );
        }


        if (
            right_col <
            LEDS_PER_ROW
        )
        {
            set_pixel_left(
                row,
                right_col,

                0,
                g_val,
                255
            );
        }
    }


    s_anim_frame++;


    return true;
}


/* ============================================================
 * WEATHER MODE
 *
 * 현재는 기본 구현.
 * 실제 디자인은 나중에 변경 가능.
 * ============================================================ */

static bool effect_weather(
    uint32_t now_ms,
    weather_type_t weather
)
{
    if (
        now_ms -
        s_last_weather_update
        <
        100
    )
    {
        return false;
    }


    s_last_weather_update =
        now_ms;


    clear_all_leds();


    uint8_t r = 0;
    uint8_t g = 0;
    uint8_t b = 0;


    switch (weather)
    {
        case WEATHER_CLEAR:
        {
            r = 120;
            g = 100;
            b = 10;

            break;
        }


        case WEATHER_CLOUDY:
        {
            r = 50;
            g = 50;
            b = 50;

            break;
        }


        case WEATHER_RAIN:
        {
            r = 0;
            g = 40;
            b = 150;

            break;
        }


        case WEATHER_SNOW:
        {
            r = 100;
            g = 100;
            b = 100;

            break;
        }


        default:
        {
            break;
        }
    }


    for (
        uint8_t row = 0;
        row < LED_NUM_ROWS;
        row++
    )
    {
        for (
            uint8_t col = 0;
            col < LEDS_PER_ROW;
            col++
        )
        {
            set_pixel_right(
                row,
                col,
                r,
                g,
                b
            );


            set_pixel_left(
                row,
                col,
                r,
                g,
                b
            );
        }
    }


    return true;
}


/* ============================================================
 * MUSIC MODE
 *
 * 현재는 EQ byte를 column 높이로 표현.
 *
 * WROOM EQ 형식 확정 후 여기만 변경하면 됨.
 * ============================================================ */

static bool effect_music(
    uint32_t now_ms
)
{
    if (
        now_ms -
        s_last_music_update
        <
        30
    )
    {
        return false;
    }


    s_last_music_update =
        now_ms;


    clear_all_leds();


    if (
        s_latest_eq.length != LED_EQ_BANDS
        || !led_eq_is_fresh(s_have_eq, s_last_eq_ms, now_ms)
    )
    {
        return true;
    }


    /*
     * 31 column에 EQ band를 매핑
     */

    for (
        uint8_t col = 0;
        col < LEDS_PER_ROW;
        col++
    )
    {
        uint8_t eq_index =
            (uint8_t)(
                ((uint16_t)col * s_latest_eq.length)
                /
                LEDS_PER_ROW
            );

        if (
            eq_index >=
            s_latest_eq.length
        )
        {
            eq_index =
                s_latest_eq.length -
                1;
        }


        uint8_t level =
            s_latest_eq.data[
                eq_index
            ];


        /*
         * WROOM에서 EQ 값을 0~255로 준다고 가정.
         * 0~255 → 0~4 row
         */

        uint8_t bars =
            (uint8_t)(
                ((uint16_t)level * LED_NUM_ROWS)
                /
                255U
            );


        if (
            level > 0 &&
            bars == 0
        )
        {
            bars = 1;
        }


        for (
            uint8_t row = 0;
            row < LED_NUM_ROWS;
            row++
        )
        {
            if (
                row <
                bars
            )
            {
                /*
                 * 아래쪽부터 올라가는 느낌은
                 * 실제 장착 방향 확정 후 row 반전 가능.
                 */

                uint8_t r =
                    level;

                uint8_t g =
                    255 -
                    level;

                uint8_t b =
                    80;


                set_pixel_right(
                    row,
                    col,
                    r,
                    g,
                    b
                );


                set_pixel_left(
                    row,
                    col,
                    r,
                    g,
                    b
                );
            }
        }
    }


    return true;
}


/* ============================================================
 * HANDLE COMMAND
 * ============================================================ */

static void handle_command(
    const led_command_t *cmd
)
{
    switch (cmd->type)
    {
        case LED_COMMAND_START:
        {
            system_state_set_led_enabled(
                true
            );

            ESP_LOGI(
                TAG,
                "LED START"
            );

            break;
        }


        case LED_COMMAND_STOP:
        {
            system_state_set_led_enabled(
                false
            );


            led_output_off();


            ESP_LOGI(
                TAG,
                "LED STOP"
            );

            break;
        }


        case LED_COMMAND_SET_MODE:
        {
            system_state_set_led_mode(
                cmd->mode
            );


            /*
             * 모드 바뀔 때 animation reset
             */
            s_anim_frame =
                0;


            ESP_LOGI(
                TAG,
                "LED MODE=%d",
                cmd->mode
            );

            break;
        }


        case LED_COMMAND_SET_WEATHER:
        {
            system_state_set_weather(
                cmd->weather
            );


            ESP_LOGI(
                TAG,
                "WEATHER=%d",
                cmd->weather
            );

            break;
        }


        default:
        {
            break;
        }
    }
}


/* ============================================================
 * INIT HARDWARE
 * ============================================================ */
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


/* ============================================================
 * INIT
 * ============================================================ */

void led_task_init(void)
{
    led_command_queue =
        xQueueCreate(
            8,
            sizeof(
                led_command_t
            )
        );


    /*
     * EQ는 최신값 하나만 필요.
     * xQueueOverwrite() 사용.
     */
    led_eq_queue =
        xQueueCreate(
            1,
            sizeof(
                led_eq_data_t
            )
        );


    if (
        led_command_queue ==
        NULL ||
        led_eq_queue ==
        NULL
    )
    {
        ESP_LOGE(
            TAG,
            "Queue create failed"
        );

        abort();
    }


    memset(
        &s_latest_eq,
        0,
        sizeof(
            s_latest_eq
        )
    );


    clear_all_leds();


    init_strip(
        LED_DATA_PIN_RIGHT,
        &s_strip_right
    );


    init_strip(
        LED_DATA_PIN_LEFT,
        &s_strip_left
    );


    s_output_currently_off =
        true;


    ESP_LOGI(
        TAG,
        "WS2812 initialized"
    );


    ESP_LOGI(
        TAG,
        "RIGHT GPIO=%d LEDs=%d",
        LED_DATA_PIN_RIGHT,
        LED_NUM_PER_SIDE
    );


    ESP_LOGI(
        TAG,
        "LEFT GPIO=%d LEDs=%d",
        LED_DATA_PIN_LEFT,
        LED_NUM_PER_SIDE
    );
}


/* ============================================================
 * TASK
 * ============================================================ */

void led_task(
    void *arg
)
{
    (void)arg;


    led_command_t command;

    led_eq_data_t eq;


    while (1)
    {
        /* ----------------------------------------------------
         * 일반 LED 명령 처리
         * ---------------------------------------------------- */

        while (
            xQueueReceive(
                led_command_queue,
                &command,
                0
            )
            ==
            pdTRUE
        )
        {
            handle_command(
                &command
            );
        }


        /* ----------------------------------------------------
         * 최신 EQ
         * ---------------------------------------------------- */

        if (
            xQueueReceive(
                led_eq_queue,
                &eq,
                0
            )
            ==
            pdTRUE
        )
        {
            memcpy(
                &s_latest_eq,
                &eq,
                sizeof(eq)
            );
            s_last_eq_ms = (uint32_t)(esp_timer_get_time()/1000);
            s_have_eq = true;
        }


        /* ----------------------------------------------------
         * 현재 시스템 상태 읽기
         * ---------------------------------------------------- */

        p4_system_state_t state;


        system_state_get(
            &state
        );
        if (state.call_active || !state.music_playing) {
            s_latest_eq.length = 0;
            s_have_eq = false;
        }


        /*
         * LED가 원래 OFF인 경우
         */
        if (
            !state.led_enabled
        )
        {
            led_output_off();

            vTaskDelay(1);

            continue;
        }


        /*
         * Sleep 기능 때문에 실제 출력만 OFF.
         *
         * led_enabled나 led_mode는 변경하지 않음.
         */
        if (
            state.sleep_active
        )
        {
            led_output_off();

            vTaskDelay(1);

            continue;
        }


        uint32_t now_ms =
            (
                uint32_t
            )
            (
                esp_timer_get_time()
                /
                1000
            );


        bool need_show =
            false;


        switch (
            state.led_mode
        )
        {
            case LED_MODE_BASIC:
            {
                need_show =
                    effect_basic(
                        now_ms
                    );

                break;
            }


            case LED_MODE_WEATHER:
            {
                need_show =
                    effect_weather(
                        now_ms,
                        state.weather_type
                    );

                break;
            }


            case LED_MODE_MUSIC:
            {
                need_show =
                    effect_music(
                        now_ms
                    );

                break;
            }


            default:
            {
                led_output_off();

                break;
            }
        }


        if (
            need_show
        )
        {
            led_show_all();
        }

        vTaskDelay(1);
    }
}