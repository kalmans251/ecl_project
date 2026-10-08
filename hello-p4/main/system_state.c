#include <string.h>

#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"

#include "esp_timer.h"

#include "system_state.h"


/* ============================================================
 * INTERNAL STATE
 * ============================================================ */

static p4_system_state_t s_state;


static SemaphoreHandle_t s_state_mutex =
    NULL;


/* ============================================================
 * LOCK
 * ============================================================ */

static void lock_state(void)
{
    if (s_state_mutex != NULL)
    {
        xSemaphoreTake(
            s_state_mutex,
            portMAX_DELAY
        );
    }
}


static void unlock_state(void)
{
    if (s_state_mutex != NULL)
    {
        xSemaphoreGive(
            s_state_mutex
        );
    }
}


/* ============================================================
 * INIT
 * ============================================================ */

void system_state_init(void)
{
    memset(
        &s_state,
        0,
        sizeof(s_state)
    );


    s_state_mutex =
        xSemaphoreCreateMutex();


    /*
     * 기본값
     */

    s_state.led_enabled =
        false;

    s_state.led_mode =
        LED_MODE_BASIC;

    s_state.weather_type =
        WEATHER_CLEAR;


    s_state.music_enabled =
        false;

    s_state.music_playing =
        false;


    s_state.projector_enabled =
        false;


    s_state.sleep_mode_enabled =
        false;

    s_state.sleep_active =
        false;

    s_state.person_detected =
        false;

    s_state.last_person_seen_ms =
        esp_timer_get_time() / 1000;


    s_state.power_mode =
        POWER_MODE_AUTO;

    s_state.power_source =
        POWER_SOURCE_BATTERY;

    s_state.call_active =
        false;
}


/* ============================================================
 * GET SNAPSHOT
 * ============================================================ */

void system_state_get(
    p4_system_state_t *state
)
{
    if (state == NULL)
    {
        return;
    }


    lock_state();


    memcpy(
        state,
        &s_state,
        sizeof(
            p4_system_state_t
        )
    );


    unlock_state();
}


/* ============================================================
 * LED
 * ============================================================ */

void system_state_set_led_enabled(
    bool enabled
)
{
    lock_state();

    s_state.led_enabled =
        enabled;

    unlock_state();
}


void system_state_set_led_mode(
    led_mode_t mode
)
{
    lock_state();

    s_state.led_mode =
        mode;

    unlock_state();
}


void system_state_set_weather(
    weather_type_t weather
)
{
    lock_state();

    s_state.weather_type =
        weather;

    unlock_state();
}


/* ============================================================
 * MUSIC
 * ============================================================ */

void system_state_set_music_enabled(
    bool enabled
)
{
    lock_state();

    s_state.music_enabled =
        enabled;

    unlock_state();
}

void system_state_set_music_playing(
    bool playing
)
{
    lock_state();

    s_state.music_playing =
        playing;

    unlock_state();
}


/* ============================================================
 * PROJECTOR
 * ============================================================ */

void system_state_set_projector_enabled(
    bool enabled
)
{
    lock_state();

    s_state.projector_enabled =
        enabled;

    unlock_state();
}


/* ============================================================
 * SLEEP
 * ============================================================ */

void system_state_set_sleep_mode_enabled(
    bool enabled
)
{
    lock_state();


    s_state.sleep_mode_enabled =
        enabled;


    /*
     * 슬립기능 자체를 OFF하면
     * 실제 sleep_active도 즉시 해제
     */
    if (!enabled)
    {
        s_state.sleep_active =
            false;
    }


    unlock_state();
}


void system_state_set_sleep_active(
    bool active
)
{
    lock_state();

    s_state.sleep_active =
        active;

    unlock_state();
}


void system_state_set_person_detected(
    bool detected
)
{
    lock_state();


    s_state.person_detected =
        detected;


    if (detected)
    {
        s_state.last_person_seen_ms =
            esp_timer_get_time() /
            1000;
    }


    unlock_state();
}


/* ============================================================
 * POWER MODE
 * ============================================================ */

void system_state_set_power_mode(
    power_mode_t mode
)
{
    lock_state();

    s_state.power_mode =
        mode;

    unlock_state();
}

void system_state_set_power_source(
    power_source_t source
)
{
    lock_state();

    s_state.power_source =
        source;

    unlock_state();
}

/* ============================================================
 * CALL
 * ============================================================ */

void system_state_set_call_active(
    bool active
)
{
    lock_state();

    s_state.call_active =
        active;

    unlock_state();
}
void system_state_set_led_pattern(led_mode_t mode,uint8_t pattern) {
    lock_state();
    if(mode==LED_MODE_BASIC && pattern<6)s_state.led_basic_pattern=pattern;
    if(mode==LED_MODE_MUSIC && pattern<3)s_state.led_music_pattern=pattern;
    unlock_state();
}
