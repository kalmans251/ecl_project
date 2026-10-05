#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>


bool audio_output_init(
    uint32_t sample_rate
);


bool audio_output_set_sample_rate(
    uint32_t sample_rate
);


bool audio_output_write(
    const int16_t *pcm,
    size_t sample_count
);


void audio_output_set_volume(
    uint8_t volume_percent
);


uint8_t audio_output_get_volume(void);


uint32_t audio_output_get_sample_rate(void);


void audio_output_deinit(void);


bool audio_output_is_initialized(void);
/* Exclusive task ownership during voice playback. */
bool audio_output_claim(void);
void audio_output_release(void);
