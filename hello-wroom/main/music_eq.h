#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
bool music_eq_init(void);
void music_eq_reset(void);
void music_eq_clear(void);
/* Copies PCM only; FFT and logging run in the low-priority EQ task. */
void music_eq_feed(const int16_t *stereo, size_t samples, unsigned rate);
