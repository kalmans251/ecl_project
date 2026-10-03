#include "power_control.h"

#include "driver/gpio.h"

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "esp_log.h"

#include "board_config.h"


static const char *TAG =
    "POWER";


static bool s_ac_enabled =
    false;


static bool s_battery_enabled =
    true;


/* ============================================================
 * INIT
 *
 * 부팅 기본:
 *
 * AC       = OFF
 * BATTERY  = ON
 * ============================================================ */

void power_control_init(void)
{
    gpio_config_t config =
    {
        .pin_bit_mask =
            (1ULL << AC_POWER_GPIO)
            |
            (1ULL << BATTERY_POWER_GPIO),

        .mode =
            GPIO_MODE_OUTPUT,

        .pull_up_en =
            GPIO_PULLUP_DISABLE,

        .pull_down_en =
            GPIO_PULLDOWN_DISABLE,

        .intr_type =
            GPIO_INTR_DISABLE,
    };


    ESP_ERROR_CHECK(
        gpio_config(
            &config
        )
    );


    /* ========================================================
     * 상전 OFF
     *
     * GPIO2 LOW
     * ======================================================== */

    ESP_ERROR_CHECK(
        gpio_set_level(
            AC_POWER_GPIO,
            0
        )
    );


    /* ========================================================
     * 배터리 ON
     *
     * GPIO6 LOW
     *
     * Active Low
     * ======================================================== */

    ESP_ERROR_CHECK(
        gpio_set_level(
            BATTERY_POWER_GPIO,
            0
        )
    );


    s_ac_enabled =
        false;

    s_battery_enabled =
        true;


    ESP_LOGI(
        TAG,
        "BOOT: AC=OFF / BATTERY=ON"
    );
}


/* ============================================================
 * AC
 *
 * true  -> GPIO2 HIGH
 * false -> GPIO2 LOW
 * ============================================================ */

void power_control_set_ac(
    bool enabled
)
{
    ESP_ERROR_CHECK(
        gpio_set_level(
            AC_POWER_GPIO,
            enabled ? 1 : 0
        )
    );


    s_ac_enabled =
        enabled;


    ESP_LOGI(
        TAG,
        "AC -> %s",
        enabled
            ? "ON"
            : "OFF"
    );
}


/* ============================================================
 * BATTERY
 *
 * true  -> GPIO6 LOW
 * false -> GPIO6 HIGH
 *
 * Active Low
 * ============================================================ */

void power_control_set_battery(
    bool enabled
)
{
    ESP_ERROR_CHECK(
        gpio_set_level(
            BATTERY_POWER_GPIO,
            enabled ? 0 : 1
        )
    );


    s_battery_enabled =
        enabled;


    ESP_LOGI(
        TAG,
        "BATTERY -> %s",
        enabled
            ? "ON"
            : "OFF"
    );
}


/* ============================================================
 * BATTERY -> AC
 *
 * 배터리 먼저 분리
 * 잠깐 대기
 * 상전 연결
 * ============================================================ */

void power_control_select_ac(void)
{
    /*
     * 새 전원 먼저 연결
     */
    power_control_set_ac(
        true
    );

    /*
     * 전원 안정화 시간
     */
    vTaskDelay(
        pdMS_TO_TICKS(50)
    );

    /*
     * 기존 배터리 분리
     */
    power_control_set_battery(
        false
    );
}


/* ============================================================
 * AC -> BATTERY
 *
 * 상전 먼저 차단
 * 잠깐 대기
 * 배터리 연결
 * ============================================================ */

void power_control_select_battery(void)
{
    /*
     * 새 전원 먼저 연결
     */
    power_control_set_battery(
        true
    );

    /*
     * 전원 안정화 시간
     */
    vTaskDelay(
        pdMS_TO_TICKS(50)
    );

    /*
     * 기존 상전 분리
     */
    power_control_set_ac(
        false
    );
}


/* ============================================================
 * GET
 * ============================================================ */

bool power_control_get_ac(void)
{
    return s_ac_enabled;
}


bool power_control_get_battery(void)
{
    return s_battery_enabled;
}