#include "protocol.h"

#include <string.h>


uint16_t protocol_crc16_ccitt_false(
    const uint8_t *data,
    size_t len
)
{
    uint16_t crc =
        0xFFFF;


    for (
        size_t i = 0;
        i < len;
        i++
    )
    {
        crc ^=
            (uint16_t)data[i]
            <<
            8;


        for (
            int bit = 0;
            bit < 8;
            bit++
        )
        {
            if (
                crc &
                0x8000
            )
            {
                crc =
                    (uint16_t)(
                        (crc << 1)
                        ^
                        0x1021
                    );
            }
            else
            {
                crc <<=
                    1;
            }
        }
    }


    return crc;
}


/* ============================================================
 * FRAME INIT
 * ============================================================ */

void protocol_frame_init(
    protocol_frame_t *frame,
    uint8_t railing_id,
    uint8_t src,
    uint8_t dst,
    uint8_t service,
    uint8_t cmd
)
{
    if (
        frame ==
        NULL
    )
    {
        return;
    }


    memset(
        frame,
        0,
        sizeof(*frame)
    );


    frame->railing_id =
        railing_id;

    frame->src =
        src;

    frame->dst =
        dst;

    frame->service =
        service;

    frame->cmd =
        cmd;
}


/* ============================================================
 * ENCODE
 * ============================================================ */

bool protocol_encode(
    const protocol_frame_t *frame,
    uint8_t *out,
    size_t out_size,
    size_t *out_len
)
{
    if (
        frame == NULL ||
        out == NULL ||
        out_len == NULL
    )
    {
        return false;
    }


    if (
        frame->payload_len >
        PROTOCOL_MAX_PAYLOAD
    )
    {
        return false;
    }


    size_t total_len =
        10 +
        frame->payload_len;


    if (
        out_size <
        total_len
    )
    {
        return false;
    }


    out[0] =
        PROTOCOL_SOF1;

    out[1] =
        PROTOCOL_SOF2;

    out[2] =
        frame->payload_len;

    out[3] =
        frame->railing_id;

    out[4] =
        frame->src;

    out[5] =
        frame->dst;

    out[6] =
        frame->service;

    out[7] =
        frame->cmd;


    if (
        frame->payload_len >
        0
    )
    {
        memcpy(
            &out[8],
            frame->payload,
            frame->payload_len
        );
    }


    uint16_t crc =
        protocol_crc16_ccitt_false(
            &out[2],
            6 +
            frame->payload_len
        );


    out[
        8 +
        frame->payload_len
    ] =
        (uint8_t)(
            crc >>
            8
        );


    out[
        9 +
        frame->payload_len
    ] =
        (uint8_t)(
            crc &
            0xFF
        );


    *out_len =
        total_len;


    return true;
}


/* ============================================================
 * DECODE
 * ============================================================ */

bool protocol_decode(
    const uint8_t *data,
    size_t len,
    protocol_frame_t *out
)
{
    if (
        data == NULL ||
        out == NULL
    )
    {
        return false;
    }


    if (
        len <
        10
    )
    {
        return false;
    }


    if (
        data[0] !=
        PROTOCOL_SOF1
        ||
        data[1] !=
        PROTOCOL_SOF2
    )
    {
        return false;
    }


    uint8_t payload_len =
        data[2];


    if (
        payload_len >
        PROTOCOL_MAX_PAYLOAD
    )
    {
        return false;
    }


    size_t expected_len =
        10 +
        payload_len;


    if (
        len !=
        expected_len
    )
    {
        return false;
    }


    uint16_t received_crc =
        (
            (uint16_t)
            data[
                8 +
                payload_len
            ]
            <<
            8
        )
        |
        data[
            9 +
            payload_len
        ];


    uint16_t calculated_crc =
        protocol_crc16_ccitt_false(
            &data[2],
            6 +
            payload_len
        );


    if (
        received_crc !=
        calculated_crc
    )
    {
        return false;
    }


    memset(
        out,
        0,
        sizeof(*out)
    );


    out->payload_len =
        payload_len;

    out->railing_id =
        data[3];

    out->src =
        data[4];

    out->dst =
        data[5];

    out->service =
        data[6];

    out->cmd =
        data[7];


    if (
        payload_len >
        0
    )
    {
        memcpy(
            out->payload,
            &data[8],
            payload_len
        );
    }


    return true;
}