#include <Arduino.h>
#include <string.h>
#include <atomic>

#include "board_config.h"
#include "protocol.h"
#include "audio_session.h"
#include "ble_link.h"
#include "microphone_codec2.h"


static std::atomic<uint32_t> s_session{0};
static uint32_t s_ptt_request;

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
    if(f->src!=NODE_P4 || f->railing_id!=RAILING_ID)return false;
    unsigned offset=f->command==CMD_SET?1:0;
    if(f->length!=(f->command==CMD_SET?9:4))return false;
    const uint8_t *p=f->payload+offset;
    uint32_t id=((uint32_t)p[0]<<24)|((uint32_t)p[1]<<16)|((uint32_t)p[2]<<8)|p[3];
    if(!id && f->command!=CMD_STOP)return false;
    if(f->command==CMD_START){
        if(id==s_session)return s_active;
        audio_session_stop();s_session=id;s_ptt_request=0;audio_session_start();return true;
    }
    if(f->command==CMD_STOP && !s_active)return true;
    if(id!=s_session)return false;
    if(!s_active)return false;
    if(f->command==CMD_STOP){audio_session_stop();return true;}
    if(f->command==CMD_SET) {
        p=f->payload+5;
        uint32_t request=((uint32_t)p[0]<<24)|((uint32_t)p[1]<<16)|((uint32_t)p[2]<<8)|p[3];
        if(request<s_ptt_request)return false;
        if(request==s_ptt_request)return f->payload[0]==s_direction;
        if(!audio_session_set_direction(f->payload[0]))return false;
        s_ptt_request=request;return true;
    }
    return false;
}

void audio_session_report_readiness(const protocol_frame_t *f) {
    const protocol_frame_t *original=f;
    protocol_frame_t query={};
    bool health=f->command==CMD_CALL_HEALTH;
    if(health) {
        if(f->src!=NODE_P4 || f->dst!=NODE_S3 || f->service!=SERVICE_AUDIO ||
           f->railing_id!=RAILING_ID || f->length!=13)return;
        query=*f;query.command=CMD_SET;query.length=9;f=&query;
    }
    if(f->src!=NODE_P4 || f->railing_id!=RAILING_ID ||
       (f->command!=CMD_START && f->command!=CMD_SET && f->command!=CMD_STOP) ||
       f->length!=(f->command==CMD_SET?9:4))return;
    const uint8_t *p=f->payload+(f->command==CMD_SET?1:0);
    uint32_t id=((uint32_t)p[0]<<24)|((uint32_t)p[1]<<16)|((uint32_t)p[2]<<8)|p[3];
    p=f->payload+5;
    uint32_t request=f->command==CMD_SET?((uint32_t)p[0]<<24)|((uint32_t)p[1]<<16)|((uint32_t)p[2]<<8)|p[3]:0;
    uint8_t direction=f->command==CMD_SET?f->payload[0]:(f->command==CMD_START?AUDIO_DIRECTION_FIELD_TX:0);
    bool match=id && id==s_session && (f->command!=CMD_SET || request==s_ptt_request);
    if(f->command==CMD_STOP && !s_active)match=true;
    bool target=f->command==CMD_STOP?!s_active:(s_active && s_direction==direction);
    protocol_frame_t reply={};
    reply.railing_id=RAILING_ID;reply.src=NODE_S3;reply.dst=NODE_P4;
    reply.service=SERVICE_AUDIO;reply.command=CMD_DATA;reply.length=12;
    reply.payload[0]=AUDIO_DATA_READY;reply.payload[1]=f->command;
    reply.payload[2]=direction;reply.payload[3]=match && target?microphone_codec2_readiness():2;
    memcpy(reply.payload+4,f->payload+(f->command==CMD_SET?1:0),4);
    if(f->command==CMD_SET)memcpy(reply.payload+8,f->payload+5,4);
    if(health) {
        reply.payload[0]=AUDIO_DATA_HEALTH;
        memcpy(reply.payload+12,original->payload+9,4);reply.length=16;
    }
    ble_send_frame(&reply);
}
