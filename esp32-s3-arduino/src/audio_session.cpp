#include <Arduino.h>
#include <string.h>
#include <atomic>

#include "board_config.h"
#include "protocol.h"
#include "audio_session.h"
#include "ble_link.h"
#include "microphone_codec2.h"


static std::atomic<uint32_t> s_session{0};

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
    microphone_codec2_set_enabled(true);
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
    microphone_codec2_set_enabled(false);
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


    if (direction != s_direction) {
        microphone_codec2_set_enabled(
            s_active && direction == AUDIO_DIRECTION_FIELD_TX);
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
    uint16_t sequence,
    uint32_t session_id
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
        (!audio_session_field_tx_enabled() || !session_id || session_id != s_session)
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
        AUDIO_CODEC2_MODE_2400;

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


    frame.payload[7]=session_id>>24;
    frame.payload[8]=session_id>>16;
    frame.payload[9]=session_id>>8;
    frame.payload[10]=session_id;

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

uint32_t audio_session_id(void) { return s_session; }
bool audio_session_control(const protocol_frame_t *f) {
    if(f->src!=NODE_P4)return false;
    unsigned offset=f->command==CMD_SET?1:0;
    if(f->length!=offset+4)return false;
    const uint8_t *p=f->payload+offset;
    uint32_t id=((uint32_t)p[0]<<24)|((uint32_t)p[1]<<16)|((uint32_t)p[2]<<8)|p[3];
    if(!id)return false;
    if(f->command==CMD_START){
        if(id==s_session)return s_active;
        audio_session_stop();s_session=id;audio_session_start();return true;
    }
    if(id!=s_session || !s_active)return false;
    if(f->command==CMD_STOP){audio_session_stop();return true;}
    if(f->command==CMD_SET)return audio_session_set_direction(f->payload[0]);
    return false;
}
