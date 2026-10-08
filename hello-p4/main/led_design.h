#pragma once
#include <stdbool.h>
#include <stdint.h>

/* Rendering is independent of FreeRTOS, UART and the LED driver. */
#define LED_DESIGN_ROWS 4
#define LED_DESIGN_COLS 31
#define LED_DESIGN_PIXELS (LED_DESIGN_ROWS * LED_DESIGN_COLS)
#define LED_BASIC_PATTERNS 6
#define LED_MUSIC_PATTERNS 3

typedef struct { uint8_t r, g, b; } led_rgb_t;
typedef struct {
    bool active;
    uint8_t row, col, life, speed, peak;
    led_rgb_t color;
} led_spark_t;
typedef struct {
    uint32_t frame, last_ms, cycle_ms, random_state;
    uint8_t mode, weather, pattern, sunny_pattern;
    bool initialized, alert, music_valid;
    float peak, smooth;
    led_spark_t sparks[18];
    led_rgb_t pixels[2][LED_DESIGN_PIXELS];
} led_design_t;

void led_design_init(led_design_t *design, uint32_t seed);
/* mode: BASIC=1, WEATHER=2, MUSIC=3; patterns are zero based.
 * Output channels preserve the reference firmware's actual set_pixel arguments,
 * not its BGR variable names. Hardware writes these as standard RGB. */
bool led_design_render(led_design_t *design, uint32_t now_ms,
                       uint8_t mode, uint8_t weather, uint8_t pattern,
                       bool alert, bool music_valid, const uint8_t bands[8]);
uint16_t led_design_index(unsigned row, unsigned col);
