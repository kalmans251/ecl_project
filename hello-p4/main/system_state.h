#pragma once

#include <stdbool.h>
#include <stdint.h>


/* ============================================================
 * LED MODE
 * ============================================================ */

typedef enum
{
    LED_MODE_BASIC = 0x01,

    LED_MODE_WEATHER = 0x02,

    LED_MODE_MUSIC = 0x03

} led_mode_t;


/* ============================================================
 * WEATHER TYPE
 *
 * 세부 날씨 효과는 나중에 확장 가능
 * ============================================================ */

typedef enum
{
    WEATHER_CLEAR = 0x00,

    WEATHER_CLOUDY = 0x01,

    WEATHER_RAIN = 0x02,

    WEATHER_SNOW = 0x03

} weather_type_t;


/* ============================================================
 * POWER MODE
 *
 * 전력제어 단계에서 사용 예정
 * ============================================================ */

typedef enum
{
    POWER_MODE_AUTO = 0x00,

    POWER_MODE_AC = 0x01,

    POWER_MODE_BATTERY = 0x02

} power_mode_t;


typedef enum
{
    POWER_SOURCE_AC = 0x00,

    POWER_SOURCE_BATTERY = 0x01

} power_source_t;


/* ============================================================
 * SYSTEM STATE
 * ============================================================ */

typedef struct
{
    /* --------------------------------------------------------
     * LED
     * -------------------------------------------------------- */

    bool led_enabled;

    led_mode_t led_mode;

    weather_type_t weather_type;


    /* --------------------------------------------------------
     * MUSIC
     *
     * 실제 음악은 WROOM이 담당
     * -------------------------------------------------------- */

    bool music_enabled;

    bool music_playing;

    /* --------------------------------------------------------
     * PROJECTOR
     * -------------------------------------------------------- */

    bool projector_enabled;


    /* --------------------------------------------------------
     * SLEEP
     *
     * sleep_mode_enabled:
     *   슬립 기능을 사용할 것인가
     *
     * sleep_active:
     *   현재 실제로 출력이 정지된 상태인가
     * -------------------------------------------------------- */

    bool sleep_mode_enabled;

    bool sleep_active;

    bool person_detected;

    /* ============================================================
    * CALL
    * ============================================================ */

    bool call_active;


    int64_t last_person_seen_ms;


    /* --------------------------------------------------------
     * POWER
     * -------------------------------------------------------- */

    power_mode_t power_mode;

    power_source_t power_source;

    float battery_voltage;

    float battery_current;

    float battery_watt;

    uint8_t battery_percent;

} p4_system_state_t;


/* ============================================================
 * API
 * ============================================================ */

void system_state_init(void);


void system_state_get(
    p4_system_state_t *state
);


/* LED */

void system_state_set_led_enabled(
    bool enabled
);

void system_state_set_led_mode(
    led_mode_t mode
);

void system_state_set_weather(
    weather_type_t weather
);


/* MUSIC */

void system_state_set_music_enabled(
    bool enabled
);

void system_state_set_music_playing(
    bool playing
);


/* PROJECTOR */

void system_state_set_projector_enabled(
    bool enabled
);


/* SLEEP */

void system_state_set_sleep_mode_enabled(
    bool enabled
);

void system_state_set_sleep_active(
    bool active
);

void system_state_set_person_detected(
    bool detected
);


/* POWER */
void system_state_set_power_mode(
    power_mode_t mode
);

void system_state_set_power_source(
    power_source_t source
);


/* CALL */
void system_state_set_call_active(
    bool active
);