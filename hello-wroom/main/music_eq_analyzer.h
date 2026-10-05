#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#define MUSIC_EQ_BANDS 8
#define MUSIC_EQ_FFT_SIZE 256
/* EQ worker owns this state. 16kHz analysis, 10Hz display updates. */
typedef struct {
    float real[MUSIC_EQ_FFT_SIZE], imag[MUSIC_EQ_FFT_SIZE];
    float window[MUSIC_EQ_FFT_SIZE], smoothed[MUSIC_EQ_BANDS];
    unsigned filled, report_samples, input_rate, phase, average_count;
    float average_sum, reference;
} music_eq_analyzer_t;
void music_eq_analyzer_reset(music_eq_analyzer_t *s);
bool music_eq_analyze(music_eq_analyzer_t *s, const int16_t *mono,
                      size_t frames, unsigned rate,
                      uint8_t levels[MUSIC_EQ_BANDS]);
