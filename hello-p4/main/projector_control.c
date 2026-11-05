#include "projector_control.h"
#include "system_state.h"

#include "driver/gpio.h"

#include "esp_log.h"

#include "board_config.h"


static const char *TAG =
    "PROJECTOR";


static bool s_projector_enabled =
    false;


/* ============================================================
 * INIT
 *
 * 부팅 시 사용 설정에 맞춰 출력 (기본 ON)
 * GPIO11 HIGH = ON
 * ============================================================ */

void projector_control_init(void)
{
    p4_system_state_t state;
    system_state_get(&state);

    gpio_config_t config =
    {
        .pin_bit_mask =
            (1ULL << PROJECTOR_GPIO),

        .mode =
            GPIO_MODE_OUTPUT,

        .pull_up_en =
            GPIO_PULLUP_DISABLE,

        .pull_down_en =
            GPIO_PULLDOWN_ENABLE,

        .intr_type =
            GPIO_INTR_DISABLE,
    };


    ESP_ERROR_CHECK(
        gpio_config(
            &config
        )
    );


    ESP_ERROR_CHECK(
        gpio_set_level(
            PROJECTOR_GPIO,
            state.projector_enabled ? 1 : 0
        )
    );


    s_projector_enabled =
        state.projector_enabled;


    ESP_LOGI(
        TAG,
        "GPIO%d -> %s",
        PROJECTOR_GPIO,
        s_projector_enabled ? "ON" : "OFF"
    );
}


/* ============================================================
 * ON / OFF
 *
 * true  = HIGH
 * false = LOW
 * ============================================================ */

void projector_control_set(
    bool enabled
)
{
    ESP_ERROR_CHECK(
        gpio_set_level(
            PROJECTOR_GPIO,
            enabled ? 1 : 0
        )
    );


    s_projector_enabled =
        enabled;


    ESP_LOGI(
        TAG,
        "PROJECTOR -> %s",
        enabled
            ? "ON"
            : "OFF"
    );
}


bool projector_control_get(void)
{
    return s_projector_enabled;
}