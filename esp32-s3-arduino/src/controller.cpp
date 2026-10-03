#include <Arduino.h>
#include <string.h>

#include "board_config.h"
#include "protocol.h"
#include "controller.h"
#include "ble_link.h"


void controller_init(void)
{
    Serial.println(
        "[CTRL] Controller initialized"
    );
}


// ============================================================
// SYSTEM
// ============================================================

static void handle_system(
    const protocol_frame_t *frame
)
{
    // --------------------------------------------------------
    // PING
    // --------------------------------------------------------

    if (
        frame->command ==
        CMD_PING
    )
    {
        protocol_frame_t response = {};

        response.railing_id =
            frame->railing_id;

        response.src =
            NODE_S3;

        response.dst =
            frame->src;

        response.service =
            SERVICE_SYSTEM;

        response.command =
            CMD_PONG;

        response.length =
            0;


        ble_send_frame(
            &response
        );

        return;
    }


    // --------------------------------------------------------
    // ECHO
    // --------------------------------------------------------

    if (
        frame->command ==
        CMD_ECHO
    )
    {
        protocol_frame_t response = {};

        response.railing_id =
            frame->railing_id;

        response.src =
            NODE_S3;

        response.dst =
            frame->src;

        response.service =
            SERVICE_SYSTEM;

        response.command =
            CMD_ECHO_RESPONSE;

        response.length =
            frame->length;


        if (
            frame->length > 0
        )
        {
            memcpy(
                response.payload,
                frame->payload,
                frame->length
            );
        }


        ble_send_frame(
            &response
        );

        return;
    }


    // --------------------------------------------------------
    // STATUS
    // --------------------------------------------------------

    if (
        frame->command ==
        CMD_STATUS_REQUEST
    )
    {
        protocol_frame_t response = {};

        response.railing_id =
            frame->railing_id;

        response.src =
            NODE_S3;

        response.dst =
            frame->src;

        response.service =
            SERVICE_SYSTEM;

        response.command =
            CMD_STATUS_RESPONSE;


        /*
         * 현재는 간단히
         * 0x01 = 정상
         */
        response.length =
            1;

        response.payload[0] =
            0x01;


        ble_send_frame(
            &response
        );

        return;
    }


    Serial.printf(
        "[CTRL] Unknown SYSTEM CMD=%02X\n",
        frame->command
    );
}


// ============================================================
// CONTROLLER
// ============================================================

void controller_handle(
    const protocol_frame_t *frame
)
{
    if (frame == nullptr)
    {
        return;
    }


    // --------------------------------------------------------
    // 다른 난간이면 무시
    // --------------------------------------------------------

    if (
        frame->railing_id !=
        RAILING_ID
    )
    {
        return;
    }


    // --------------------------------------------------------
    // S3 목적지가 아니면 무시
    // --------------------------------------------------------

    if (
        frame->dst !=
        NODE_S3
    )
    {
        return;
    }


    Serial.printf(
        "[CTRL RX] "
        "RAIL=%02X "
        "SRC=%02X "
        "DST=%02X "
        "SERVICE=%02X "
        "CMD=%02X "
        "LEN=%u\n",

        frame->railing_id,
        frame->src,
        frame->dst,
        frame->service,
        frame->command,
        frame->length
    );


    switch (
        frame->service
    )
    {
        case SERVICE_SYSTEM:
        {
            handle_system(
                frame
            );

            break;
        }


        case SERVICE_RADAR:
        {
            Serial.println(
                "[CTRL] RADAR"
            );

            break;
        }


        case SERVICE_AUDIO:
        {
            Serial.println(
                "[CTRL] AUDIO"
            );

            break;
        }


        case SERVICE_EMERGENCY:
        {
            Serial.println(
                "[CTRL] EMERGENCY"
            );

            break;
        }


        default:
        {
            Serial.printf(
                "[CTRL] Unknown service=%02X\n",
                frame->service
            );

            break;
        }
    }
}