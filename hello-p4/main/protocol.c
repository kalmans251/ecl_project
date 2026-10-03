#include "protocol.h"

#include <string.h>


/* ============================================================
 * CRC16 UPDATE
 *
 * CRC-16/CCITT-FALSE
 *
 * poly   = 0x1021
 * init   = 0xFFFF
 * xorout = 0x0000
 * ============================================================ */

uint16_t protocol_crc16_update(
    uint16_t crc,
    uint8_t data
)
{
    crc ^= ((uint16_t)data << 8);


    for (int i = 0; i < 8; i++)
    {
        if (crc & 0x8000)
        {
            crc =
                (crc << 1) ^
                0x1021;
        }
        else
        {
            crc <<= 1;
        }
    }


    return crc;
}


/* ============================================================
 * CRC16 CALCULATE
 * ============================================================ */

uint16_t protocol_crc16_calculate(
    const uint8_t *data,
    size_t len
)
{
    uint16_t crc = 0xFFFF;


    for (size_t i = 0; i < len; i++)
    {
        crc =
            protocol_crc16_update(
                crc,
                data[i]
            );
    }


    return crc;
}


/* ============================================================
 * ENCODE
 * ============================================================ */

int protocol_encode(
    const protocol_frame_t *frame,
    uint8_t *buffer,
    size_t buffer_size
)
{
    if (
        frame->length >
        PROTOCOL_MAX_PAYLOAD
    )
    {
        return -1;
    }


    size_t total_len =
        PROTOCOL_HEADER_SIZE +
        frame->length +
        PROTOCOL_CRC_SIZE;


    if (buffer_size < total_len)
    {
        return -2;
    }


    /* ========================================================
     * HEADER
     * ======================================================== */

    buffer[0] =
        FRAME_SOF1;

    buffer[1] =
        FRAME_SOF2;

    buffer[2] =
        frame->length;

    buffer[3] =
        frame->railing_id;

    buffer[4] =
        frame->src;

    buffer[5] =
        frame->dst;

    buffer[6] =
        frame->service;

    buffer[7] =
        frame->command;


    /* ========================================================
     * PAYLOAD
     * ======================================================== */

    if (frame->length > 0)
    {
        memcpy(
            &buffer[8],
            frame->payload,
            frame->length
        );
    }


    /* ========================================================
     * CRC
     *
     * CRC 대상:
     *
     * LEN
     * RAILING_ID
     * SRC
     * DST
     * SERVICE
     * CMD
     * PAYLOAD
     *
     * SOF A5 5A 제외
     * ======================================================== */

    size_t crc_data_len =
        6 +
        frame->length;


    uint16_t crc =
        protocol_crc16_calculate(
            &buffer[2],
            crc_data_len
        );


    size_t crc_index =
        PROTOCOL_HEADER_SIZE +
        frame->length;


    buffer[crc_index] =
        (uint8_t)(
            (crc >> 8) &
            0xFF
        );


    buffer[crc_index + 1] =
        (uint8_t)(
            crc &
            0xFF
        );


    return (int)total_len;
}


/* ============================================================
 * DECODE
 *
 * 연속된 완성 프레임을 Decode할 때 사용.
 * UART에서는 Parser가 주로 사용됨.
 * ============================================================ */

int protocol_decode(
    const uint8_t *buffer,
    size_t buffer_len,
    protocol_frame_t *frame
)
{
    if (
        buffer_len <
        PROTOCOL_HEADER_SIZE +
        PROTOCOL_CRC_SIZE
    )
    {
        return -1;
    }


    if (
        buffer[0] != FRAME_SOF1 ||
        buffer[1] != FRAME_SOF2
    )
    {
        return -2;
    }


    uint8_t payload_len =
        buffer[2];


    if (
        payload_len >
        PROTOCOL_MAX_PAYLOAD
    )
    {
        return -3;
    }


    size_t total_len =
        PROTOCOL_HEADER_SIZE +
        payload_len +
        PROTOCOL_CRC_SIZE;


    if (buffer_len < total_len)
    {
        return -4;
    }


    /* ========================================================
     * CRC 검증
     * ======================================================== */

    size_t crc_index =
        PROTOCOL_HEADER_SIZE +
        payload_len;


    uint16_t received_crc =
        ((uint16_t)buffer[crc_index] << 8) |
        buffer[crc_index + 1];


    uint16_t calculated_crc =
        protocol_crc16_calculate(
            &buffer[2],
            6 + payload_len
        );


    if (
        received_crc !=
        calculated_crc
    )
    {
        return -5;
    }


    /* ========================================================
     * HEADER
     * ======================================================== */

    frame->length =
        payload_len;

    frame->railing_id =
        buffer[3];

    frame->src =
        buffer[4];

    frame->dst =
        buffer[5];

    frame->service =
        buffer[6];

    frame->command =
        buffer[7];


    /* ========================================================
     * PAYLOAD
     * ======================================================== */

    if (payload_len > 0)
    {
        memcpy(
            frame->payload,
            &buffer[8],
            payload_len
        );
    }


    return (int)total_len;
}