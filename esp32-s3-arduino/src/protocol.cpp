#include "protocol.h"


// ============================================================
// CRC-16 / CCITT-FALSE
//
// poly   = 0x1021
// init   = 0xFFFF
// refin  = false
// refout = false
// xorout = 0x0000
// ============================================================

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
                (uint16_t)(
                    (crc << 1) ^
                    0x1021
                );
        }
        else
        {
            crc =
                (uint16_t)(
                    crc << 1
                );
        }
    }


    return crc;
}


uint16_t protocol_crc16(
    const uint8_t *data,
    size_t length
)
{
    uint16_t crc = 0xFFFF;


    for (size_t i = 0; i < length; i++)
    {
        crc =
            protocol_crc16_update(
                crc,
                data[i]
            );
    }


    return crc;
}


// ============================================================
// ENCODE
// ============================================================

int protocol_encode(
    const protocol_frame_t *frame,
    uint8_t *output,
    size_t output_size
)
{
    if (
        frame == nullptr ||
        output == nullptr
    )
    {
        return -1;
    }


    if (
        frame->length >
        PROTOCOL_MAX_PAYLOAD
    )
    {
        return -2;
    }


    size_t frame_size =
        PROTOCOL_HEADER_SIZE +
        frame->length +
        PROTOCOL_CRC_SIZE;


    if (output_size < frame_size)
    {
        return -3;
    }


    size_t index = 0;


    // --------------------------------------------------------
    // SOF
    // --------------------------------------------------------

    output[index++] =
        PROTOCOL_SOF1;

    output[index++] =
        PROTOCOL_SOF2;


    // --------------------------------------------------------
    // CRC START
    //
    // CRC begins at LEN
    // --------------------------------------------------------

    size_t crc_start =
        index;


    output[index++] =
        frame->length;

    output[index++] =
        frame->railing_id;

    output[index++] =
        frame->src;

    output[index++] =
        frame->dst;

    output[index++] =
        frame->service;

    output[index++] =
        frame->command;


    // --------------------------------------------------------
    // PAYLOAD
    // --------------------------------------------------------

    for (
        uint8_t i = 0;
        i < frame->length;
        i++
    )
    {
        output[index++] =
            frame->payload[i];
    }


    // --------------------------------------------------------
    // CRC
    // --------------------------------------------------------

    size_t crc_length =
        6 + frame->length;


    uint16_t crc =
        protocol_crc16(
            &output[crc_start],
            crc_length
        );


    output[index++] =
        (uint8_t)(
            (crc >> 8) & 0xFF
        );

    output[index++] =
        (uint8_t)(
            crc & 0xFF
        );


    return (int)index;
}