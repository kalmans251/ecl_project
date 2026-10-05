#pragma once

#include <stdint.h>
#include <stddef.h>


/* ============================================================
 * FRAME
 *
 * A5 5A
 * LEN
 * RAILING_ID
 * SRC
 * DST
 * SERVICE
 * CMD
 * PAYLOAD
 * CRC_H
 * CRC_L
 * ============================================================ */

#define FRAME_SOF1                  0xA5
#define FRAME_SOF2                  0x5A

#define PROTOCOL_MAX_PAYLOAD        128

#define PROTOCOL_HEADER_SIZE        8
#define PROTOCOL_CRC_SIZE           2

#define PROTOCOL_MAX_FRAME_SIZE \
    (PROTOCOL_HEADER_SIZE + \
     PROTOCOL_MAX_PAYLOAD + \
     PROTOCOL_CRC_SIZE)


/* ============================================================
 * NODE
 *
 * 실제 MCU / 통신 노드
 * ============================================================ */

typedef enum
{
    NODE_PI     = 0x01,
    NODE_P4     = 0x02,
    NODE_WROOM  = 0x03,
    NODE_S3     = 0x04

} node_id_t;


/* ============================================================
 * SERVICE
 *
 * 각 MCU 내부 기능
 * ============================================================ */

typedef enum
{
    SERVICE_SYSTEM      = 0x00,

    SERVICE_LED         = 0x01,

    SERVICE_MUSIC       = 0x02,

    SERVICE_SD          = 0x03,

    SERVICE_RADAR       = 0x04,

    SERVICE_AUDIO       = 0x05,

    SERVICE_EMERGENCY   = 0x06,

    SERVICE_POWER       = 0x07,

    SERVICE_PROJECTOR   = 0x08,
    
    SERVICE_DETECTION   = 0x09,

    SERVICE_SLEEP       = 0x0A
} service_id_t;


/* ============================================================
 * COMMAND
 *
 * 공통 명령
 * ============================================================ */

typedef enum
{
    CMD_PING             = 0x01,
    CMD_PONG             = 0x02,

    CMD_ECHO             = 0x03,
    CMD_ECHO_RESPONSE    = 0x04,

    CMD_STATUS_REQUEST   = 0x10,
    CMD_STATUS_RESPONSE  = 0x11,

    CMD_START            = 0x20,
    CMD_STOP             = 0x21,

    CMD_SET              = 0x22,
    CMD_DATA             = 0x23,

    CMD_PAUSE            = 0x24,
    CMD_RESUME           = 0x25,

    CMD_NEXT             = 0x26,
    CMD_PREVIOUS         = 0x27

} command_t;

/* ============================================================
 * AUDIO DIRECTION
 *
 * SERVICE_AUDIO + CMD_SET
 *
 * FIELD_TX
 *   현장 S3 마이크 -> 관제
 *
 * CONTROL_TX
 *   관제 마이크 -> WROOM 스피커
 * ============================================================ */

typedef enum
{
    AUDIO_DIRECTION_FIELD_TX   = 0x01,

    AUDIO_DIRECTION_CONTROL_TX = 0x02

} audio_direction_t;


/* ============================================================
 * AUDIO DATA TYPE
 *
 * SERVICE_AUDIO + CMD_DATA
 *
 * EVENT:
 *   P4 -> Pi call state synchronization
 *
 * CODEC2:
 *   reserved for the next voice-data step
 * ============================================================ */

typedef enum
{
    AUDIO_DATA_EVENT  = 0x01,

    AUDIO_DATA_CODEC2 = 0x02,

    // P4 -> Pi: [type, receive-window-ms high, receive-window-ms low].
    AUDIO_DATA_CONTROL_WINDOW = 0x03

} audio_data_type_t;


/* ============================================================
 * CODEC2 VOICE PACKET
 *
 * SERVICE_AUDIO + CMD_DATA
 *
 * payload[0]      = AUDIO_DATA_CODEC2
 * payload[1]      = CODEC2_MODE_2400
 * payload[2]      = AUDIO_DIRECTION_*
 * payload[3..4]   = packet sequence (big-endian)
 * payload[5]      = frame count
 * payload[6]      = bytes per Codec2 frame
 * payload[7..]    = concatenated Codec2 frames
 *
 * Codec2 2400:
 * 20 ms / frame, 48 bits = 6 bytes.
 * Recommended aggregation: up to 8 frames = 160 ms.
 * ============================================================ */

typedef enum
{
    CODEC2_MODE_2400 =
        0x01

} codec2_mode_t;


#define CODEC2_2400_BYTES_PER_FRAME      6
#define CODEC2_MAX_FRAMES_PER_PACKET     8
#define AUDIO_CODEC2_META_SIZE           7


/* ============================================================
 * AUDIO EVENT
 *
 * payload:
 * [0] AUDIO_DATA_EVENT
 * [1] audio_event_t
 * [2] call origin
 * [3] direction (0 when call ended)
 * ============================================================ */

typedef enum
{
    AUDIO_EVENT_CALL_STARTED      = 0x01,

    AUDIO_EVENT_CALL_ENDED        = 0x02,

    AUDIO_EVENT_DIRECTION_CHANGED = 0x03

} audio_event_t;

/* ============================================================
 * MUSIC EVENT
 *
 * WROOM -> P4
 *
 * SERVICE = SERVICE_MUSIC
 * CMD     = CMD_DATA
 *
 * payload[0] = music_event_t
 * ============================================================ */

typedef enum
{
    MUSIC_EVENT_STARTED   = 0x01,

    MUSIC_EVENT_FINISHED  = 0x02,

    MUSIC_EVENT_PAUSED    = 0x03,

    MUSIC_EVENT_RESUMED   = 0x04,

    MUSIC_EVENT_ERROR     = 0x05,

    MUSIC_EVENT_STOPPED   = 0x06
} music_event_t;

/* ============================================================
 * MUSIC PLAY MODE
 * ============================================================ */

typedef enum
{
    MUSIC_PLAY_MODE_SEQUENTIAL =
        0x01,

    MUSIC_PLAY_MODE_SHUFFLE =
        0x02,

    MUSIC_PLAY_MODE_AGE =
        0x03

} music_play_mode_t;


/* ============================================================
 * MUSIC GROUP
 * ============================================================ */

typedef enum
{
    MUSIC_GROUP_DEFAULT =
        0x00,

    MUSIC_GROUP_10S =
        0x01,

    MUSIC_GROUP_20S =
        0x02,

    MUSIC_GROUP_30S =
        0x03,

    MUSIC_GROUP_40S =
        0x04

} music_group_t;


/* ============================================================
 * MUSIC SET TYPE
 * ============================================================ */

typedef enum
{
    MUSIC_SET_PLAY_MODE =
        0x01,

    MUSIC_SET_GROUP =
        0x02,

    MUSIC_SET_VOLUME =
        0x03

} music_set_type_t;

/* ============================================================
 * Protocol Frame
 * ============================================================ */

typedef struct
{
    uint8_t railing_id;

    uint8_t src;
    uint8_t dst;

    uint8_t service;
    uint8_t command;

    uint8_t length;

    uint8_t payload[PROTOCOL_MAX_PAYLOAD];

} protocol_frame_t;


/* ============================================================
 * CRC16
 * CRC-16/CCITT-FALSE
 * ============================================================ */

uint16_t protocol_crc16_update(
    uint16_t crc,
    uint8_t data
);


uint16_t protocol_crc16_calculate(
    const uint8_t *data,
    size_t len
);


/* ============================================================
 * Protocol
 * ============================================================ */

int protocol_encode(
    const protocol_frame_t *frame,
    uint8_t *buffer,
    size_t buffer_size
);


int protocol_decode(
    const uint8_t *buffer,
    size_t buffer_len,
    protocol_frame_t *frame
);

/* ============================================================
 * SD DATA TYPE
 *
 * SERVICE_SD + CMD_DATA
 * ============================================================ */

typedef enum
{
    SD_DATA_TRACK_REQUEST =
        0x01,

    SD_DATA_TRACK_RESPONSE =
        0x02,

    SD_DATA_CATALOG_CHANGED =
        0x03

} sd_data_type_t;

/* ============================================================
 * EMERGENCY
 * ============================================================ */

typedef enum
{
    EMERGENCY_SOURCE_BUTTON =
        0x01

} emergency_source_t;


typedef enum
{
    EMERGENCY_ACTION_ACK =
        0x01

} emergency_action_t;


/* ============================================================
 * EMERGENCY EVENT
 *
 * P4 -> Pi
 * SERVICE_EMERGENCY + CMD_DATA
 * ============================================================ */

typedef enum
{
    EMERGENCY_EVENT_ACKED =
        0x01

} emergency_event_t;
