#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>


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
 * PAYLOAD...
 * CRC_H
 * CRC_L
 *
 * LEN = payload length
 *
 * CRC:
 * CRC16/CCITT-FALSE
 * Poly    = 0x1021
 * Init    = 0xFFFF
 * XorOut  = 0x0000
 *
 * CRC 범위:
 * LEN ~ PAYLOAD
 * ============================================================ */

#define PROTOCOL_SOF1               0xA5
#define PROTOCOL_SOF2               0x5A

#define PROTOCOL_MAX_PAYLOAD        128

#define PROTOCOL_MAX_FRAME_SIZE \
    (10 + PROTOCOL_MAX_PAYLOAD)


/* ============================================================
 * NODE
 * ============================================================ */

typedef enum
{
    NODE_PI =
        0x01,

    NODE_P4 =
        0x02,

    NODE_WROOM =
        0x03,

    NODE_S3 =
        0x04,

} node_id_t;


/* ============================================================
 * SERVICE
 * ============================================================ */

typedef enum
{
    SERVICE_SYSTEM =
        0x00,

    SERVICE_LED =
        0x01,

    SERVICE_MUSIC =
        0x02,

    SERVICE_SD =
        0x03,

    SERVICE_RADAR =
        0x04,

    SERVICE_AUDIO =
        0x05,

    SERVICE_EMERGENCY =
        0x06,

    SERVICE_POWER =
        0x07,

    SERVICE_PROJECTOR =
        0x08,

    SERVICE_DETECTION =
        0x09,

    SERVICE_SLEEP =
        0x0A,

} service_id_t;


/* ============================================================
 * COMMAND
 * ============================================================ */

typedef enum
{
    CMD_PING =
        0x01,

    CMD_PONG =
        0x02,

    CMD_ECHO =
        0x03,

    CMD_ECHO_RESPONSE =
        0x04,


    CMD_STATUS_REQUEST =
        0x10,

    CMD_STATUS_RESPONSE =
        0x11,


    CMD_START =
        0x20,

    CMD_STOP =
        0x21,

    CMD_SET =
        0x22,

    CMD_DATA =
        0x23,

    CMD_PAUSE =
        0x24,

    CMD_RESUME =
        0x25,

    CMD_NEXT =
        0x26,
        
    CMD_PREVIOUS =
        0x27,
} command_id_t;


/* ============================================================
 * MUSIC EVENT
 * ============================================================ */

typedef enum
{
    MUSIC_EVENT_STARTED =
        0x01,

    MUSIC_EVENT_FINISHED =
        0x02,

    MUSIC_EVENT_PAUSED =
        0x03,

    MUSIC_EVENT_RESUMED =
        0x04,

    MUSIC_EVENT_ERROR =
        0x05,

    MUSIC_EVENT_STOPPED =
        0x06

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
 *
 * AGE_GROUP 값과 맞춰둠.
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
 *
 * SERVICE_MUSIC + CMD_SET
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
 * AUDIO DIRECTION
 * ============================================================ */

typedef enum
{
    AUDIO_DIR_FIELD_TX =
        0x01,

    AUDIO_DIR_CONTROL_TX =
        0x02,

} audio_direction_t;


/* ============================================================
 * AUDIO DATA / CODEC2
 * ============================================================ */

typedef enum
{
    AUDIO_DATA_EVENT =
        0x01,

    AUDIO_DATA_CODEC2 =
        0x02

} audio_data_type_t;


typedef enum
{
    CODEC2_MODE_2400 =
        0x01

} codec2_mode_t;


#define CODEC2_2400_BYTES_PER_FRAME      6
#define CODEC2_MAX_FRAMES_PER_PACKET     8
#define AUDIO_CODEC2_META_SIZE           7


/* ============================================================
 * FRAME STRUCT
 * ============================================================ */

typedef struct
{
    uint8_t payload_len;

    uint8_t railing_id;

    uint8_t src;

    uint8_t dst;

    uint8_t service;

    uint8_t cmd;

    uint8_t payload[
        PROTOCOL_MAX_PAYLOAD
    ];

} protocol_frame_t;


/* ============================================================
 * API
 * ============================================================ */

uint16_t protocol_crc16_ccitt_false(
    const uint8_t *data,
    size_t len
);


bool protocol_encode(
    const protocol_frame_t *frame,
    uint8_t *out,
    size_t out_size,
    size_t *out_len
);


bool protocol_decode(
    const uint8_t *data,
    size_t len,
    protocol_frame_t *out
);


void protocol_frame_init(
    protocol_frame_t *frame,
    uint8_t railing_id,
    uint8_t src,
    uint8_t dst,
    uint8_t service,
    uint8_t cmd
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
