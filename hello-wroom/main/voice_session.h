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

/* Validate and enqueue CONTROL_TX packets for the dedicated playback task. */
bool voice_session_handle_codec2(
    const uint8_t *payload,
    size_t length
);

/* Only for a direction command from P4, which validates the active call. */
bool voice_session_sync_direction(audio_direction_t direction);

bool voice_session_control(const protocol_frame_t *frame);
bool voice_session_forward_allowed(const protocol_frame_t *frame);

/* Output readiness only; not yet an end-to-end P4/Pi call acknowledgement. */
typedef enum {
    VOICE_OUTPUT_IDLE,
    VOICE_OUTPUT_PREPARING,
    VOICE_OUTPUT_READY,
    VOICE_OUTPUT_STOPPING,
    VOICE_OUTPUT_FAILED,
} voice_output_state_t;
voice_output_state_t voice_session_output_state(void);

bool voice_session_readiness(const protocol_frame_t *request, protocol_frame_t *reply);
