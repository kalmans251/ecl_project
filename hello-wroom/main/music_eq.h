#pragma once
#include <stddef.h>
#include <stdint.h>
void music_eq_reset(void);
void music_eq_clear(void);
void music_eq_feed(const int16_t *stereo, size_t samples, unsigned rate, unsigned volume);
