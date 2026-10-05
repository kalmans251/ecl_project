#pragma once
#include <stdbool.h>
#include <stdint.h>
#define LED_EQ_BANDS 8U
#define LED_EQ_TIMEOUT_MS 500U
static inline bool led_eq_is_fresh(bool have, uint32_t last, uint32_t now)
{
    return have && (uint32_t)(now-last) <= LED_EQ_TIMEOUT_MS;
}
