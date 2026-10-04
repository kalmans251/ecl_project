#include <Arduino.h>

#include "protocol.h"
#include "audio_session.h"
#include "ble_link.h"


static bool
    s_active =
        false;


static uint8_t
    s_direction =
        AUDIO_DIRECTION_FIELD_TX;


void audio_session_init(void)
{
    s_active =
        false;

    s_direction =
        AUDIO_DIRECTION_FIELD_TX;


    Serial.println(
        "[AUDIO] Session ready"
    );
}


void audio_session_start(void)
{
    s_active =
        true;

    s_direction =
        AUDIO_DIRECTION_FIELD_TX;


    Serial.println(
        "[AUDIO] CALL START -> FIELD_TX"
    );
}


void audio_session_stop(void)
{
    s_active =
        false;

    s_direction =
        AUDIO_DIRECTION_FIELD_TX;


    Serial.println(
        "[AUDIO] CALL STOP"
    );
}


bool audio_session_set_direction(
    uint8_t direction
)
{
    if (
        direction !=
        AUDIO_DIRECTION_FIELD_TX
        &&
        direction !=
        AUDIO_DIRECTION_CONTROL_TX
    )
    {
        return false;
    }


    s_direction =
        direction;


    Serial.printf(
        "[AUDIO] DIRECTION -> %s\n",
        direction ==
            AUDIO_DIRECTION_CONTROL_TX
            ?
            "CONTROL_TX"
            :
            "FIELD_TX"
    );


    return true;
}


bool audio_session_is_active(void)
{
    return s_active;
}


uint8_t audio_session_get_direction(void)
{
    return s_direction;
}


bool audio_session_field_tx_enabled(void)
{
    return
        s_active
        &&
        s_direction ==
            AUDIO_DIRECTION_FIELD_TX;
}



bool audio_session_send_codec2(
    const uint8_t *data,
    uint8_t frame_count,
    uint16_t sequence
)
{
    if (
        data ==
        nullptr
        ||
        frame_count ==
        0
        ||
        frame_count >
        CODEC2_MAX_FRAMES_PER_PACKET
        ||
        !audio_session_field_tx_enabled()
    )
    {
        return false;
    }


    uint8_t data_length =
        frame_count
        *
        CODEC2_2400_BYTES_PER_FRAME;


    protocol_frame_t frame = {};


    frame.railing_id =
        RAILING_ID;

    frame.src =
        NODE_S3;

    frame.dst =
        NODE_PI;

    frame.service =
        SERVICE_AUDIO;

    frame.command =
        CMD_DATA;

    frame.length =
        AUDIO_CODEC2_META_SIZE
        +
        data_length;


    frame.payload[0] =
        AUDIO_DATA_CODEC2;

    frame.payload[1] =
        CODEC2_MODE_2400;

    frame.payload[2] =
        AUDIO_DIRECTION_FIELD_TX;

    frame.payload[3] =
        (uint8_t)(
            sequence >>
            8
        );

    frame.payload[4] =
        (uint8_t)
        sequence;

    frame.payload[5] =
        frame_count;

    frame.payload[6] =
        CODEC2_2400_BYTES_PER_FRAME;


    memcpy(
        &frame.payload[
            AUDIO_CODEC2_META_SIZE
        ],
        data,
        data_length
    );


    return
        ble_send_frame(
            &frame
        );
}
