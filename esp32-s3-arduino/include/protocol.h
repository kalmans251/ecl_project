#pragma once

#include <Arduino.h>


// ============================================================
// FRAME
//
// A5 5A
// LEN
// RAILING_ID
// SRC
// DST
// SERVICE
// CMD
// PAYLOAD
// CRC_H
// CRC_L
//
// LEN = Payload length only
// ============================================================

#define PROTOCOL_SOF1              0xA5
#define PROTOCOL_SOF2              0x5A

#define PROTOCOL_MAX_PAYLOAD       128

#define PROTOCOL_HEADER_SIZE       8
#define PROTOCOL_CRC_SIZE          2

#define PROTOCOL_MAX_FRAME_SIZE    \
    (PROTOCOL_HEADER_SIZE + \
     PROTOCOL_MAX_PAYLOAD + \
     PROTOCOL_CRC_SIZE)


// ============================================================
// NODE
// ============================================================

#define NODE_PI        0x01
#define NODE_P4        0x02
#define NODE_WROOM     0x03
#define NODE_S3        0x04


// ============================================================
// SERVICE
// ============================================================

#define SERVICE_SYSTEM       0x00
#define SERVICE_LED          0x01
#define SERVICE_MUSIC        0x02
#define SERVICE_SD           0x03
#define SERVICE_RADAR        0x04
#define SERVICE_AUDIO        0x05
#define SERVICE_EMERGENCY    0x06


// ============================================================
// COMMAND
// ============================================================

#define CMD_PING              0x01
#define CMD_PONG              0x02

#define CMD_ECHO              0x03
#define CMD_ECHO_RESPONSE     0x04

#define CMD_STATUS_REQUEST    0x10
#define CMD_STATUS_RESPONSE   0x11

#define CMD_START             0x20
#define CMD_STOP              0x21
#define CMD_SET               0x22
#define CMD_DATA              0x23


// ============================================================
// FRAME STRUCTURE
// ============================================================

typedef struct
{
    uint8_t railing_id;

    uint8_t src;
    uint8_t dst;

    uint8_t service;
    uint8_t command;

    uint8_t length;

    uint8_t payload[
        PROTOCOL_MAX_PAYLOAD
    ];

} protocol_frame_t;


// ============================================================
// CRC
// ============================================================

uint16_t protocol_crc16_update(
    uint16_t crc,
    uint8_t data
);

uint16_t protocol_crc16(
    const uint8_t *data,
    size_t length
);


// ============================================================
// ENCODE
// ============================================================

int protocol_encode(
    const protocol_frame_t *frame,
    uint8_t *output,
    size_t output_size
);