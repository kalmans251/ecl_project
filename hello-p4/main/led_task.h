#pragma once

#include <stdint.h>

#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"

#include "system_state.h"


/* ============================================================
 * COMMAND
 * ============================================================ */

typedef enum
{
    LED_COMMAND_START = 0,

    LED_COMMAND_STOP,

    LED_COMMAND_SET_MODE,

    LED_COMMAND_SET_WEATHER

} led_command_type_t;


typedef struct
{
    led_command_type_t type;

    led_mode_t mode;

    weather_type_t weather;

} led_command_t;


/* ============================================================
 * EQ DATA
 *
 * WROOM에서 넘어오는 최신 EQ
 * ============================================================ */

#define LED_EQ_MAX_DATA    32


typedef struct
{
    uint8_t length;

    uint8_t data[
        LED_EQ_MAX_DATA
    ];

} led_eq_data_t;


/* ============================================================
 * QUEUES
 * ============================================================ */

extern QueueHandle_t
    led_command_queue;

extern QueueHandle_t
    led_eq_queue;


/* ============================================================
 * API
 * ============================================================ */

void led_task_init(void);

void led_task(
    void *arg
);