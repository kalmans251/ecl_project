#pragma once

#include <Arduino.h>

void audio_session_init(void);

void audio_session_start(void);

void audio_session_stop(void);

bool audio_session_set_direction(
    uint8_t direction
);

bool audio_session_is_active(void);

uint8_t audio_session_get_direction(void);

bool audio_session_field_tx_enabled(void);
