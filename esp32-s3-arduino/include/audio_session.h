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


/*
 * Send already-encoded Codec2 2400 frames toward the Pi.
 *
 * frame_count: 1..8
 * data length : frame_count * 6 bytes
 *
 * This is only allowed while the call is active in FIELD_TX.
 */
bool audio_session_send_codec2(
    const uint8_t *data,
    uint8_t frame_count,
    uint16_t sequence
);
