#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "protocol.h"


void voice_session_init(void);

void voice_session_start(void);

void voice_session_stop(void);

bool voice_session_set_direction(
    audio_direction_t direction
);

bool voice_session_is_active(void);

audio_direction_t voice_session_get_direction(void);

/*
 * Accepts one SERVICE_AUDIO/CMD_DATA payload.
 *
 * The Codec2 decoder is intentionally not implemented yet.
 * For now this validates/counts CONTROL_TX Codec2 packets so
 * the Pi -> PLC -> P4 -> WROOM relay can be tested end-to-end.
 */
bool voice_session_handle_codec2(
    const uint8_t *payload,
    size_t length
);
