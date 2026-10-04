#include <Arduino.h>
#include <string.h>

#include "board_config.h"
#include "protocol.h"
#include "controller.h"
#include "ble_link.h"
#include "radar_manager.h"
#include "emergency_button.h"

void controller_init(void)
{
    Serial.println(
        "[CTRL] Controller initialized"
    );
}
static void handle_radar(
    const protocol_frame_t *frame
);

static void handle_emergency(
    const protocol_frame_t *frame
);

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
            handle_radar(
                frame
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
            handle_emergency(
                frame
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

// ============================================================
// RADAR
// ============================================================

static void handle_radar(
    const protocol_frame_t *frame
)
{
    switch (
        frame->command
    )
    {
        /*
         * 상세 좌표 송신 ON
         */
        case CMD_START:
        {
            radar_manager_set_detail_enabled(
                true
            );

            break;
        }


        /*
         * 상세 좌표 송신 OFF
         *
         * 사람 감지는 계속 동작한다.
         */
        case CMD_STOP:
        {
            radar_manager_set_detail_enabled(
                false
            );

            break;
        }


        /*
         * payload:
         *
         * [0] RADAR_SET_POSITION_SOURCE
         * [1] 1 or 2
         */
        case CMD_SET:
        {
            if (
                frame->length <
                2
            )
            {
                break;
            }


            if (
                frame->payload[0]
                ==
                RADAR_SET_POSITION_SOURCE
            )
            {
                radar_manager_set_position_source(
                    frame->payload[1]
                );
            }


            break;
        }


        case CMD_STATUS_REQUEST:
        {
            protocol_frame_t response =
                {};


            response.railing_id =
                RAILING_ID;

            response.src =
                NODE_S3;

            response.dst =
                frame->src;

            response.service =
                SERVICE_RADAR;

            response.command =
                CMD_STATUS_RESPONSE;

            response.length =
                4;


            response.payload[0] =
                radar_manager_is_detail_enabled()
                    ?
                    1
                    :
                    0;


            response.payload[1] =
                radar_manager_get_position_source();


            response.payload[2] =
                radar_manager_get_target_count(
                    1
                );


            response.payload[3] =
                radar_manager_get_target_count(
                    2
                );


            ble_send_frame(
                &response
            );


            break;
        }


        default:
        {
            break;
        }
    }
}

static void handle_emergency(
    const protocol_frame_t *frame
)
{
    switch (
        frame->command
    )
    {
        case CMD_SET:
        {
            if (
                frame->length <
                1
            )
            {
                break;
            }


            if (
                frame->payload[0]
                ==
                EMERGENCY_ACTION_ACK
            )
            {
                emergency_button_clear();

                Serial.println(
                    "[EMERGENCY] CONTROL ACK"
                );
            }


            break;
        }


        case CMD_STATUS_REQUEST:
        {
            protocol_frame_t response = {};

            response.railing_id =
                RAILING_ID;

            response.src =
                NODE_S3;

            response.dst =
                frame->src;

            response.service =
                SERVICE_EMERGENCY;

            response.command =
                CMD_STATUS_RESPONSE;

            response.length =
                1;

            response.payload[0] =
                emergency_button_is_active()
                    ? 1
                    : 0;


            ble_send_frame(
                &response
            );

            break;
        }


        default:
        {
            break;
        }
    }
}