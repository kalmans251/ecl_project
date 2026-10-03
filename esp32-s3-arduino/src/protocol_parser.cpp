#include "protocol_parser.h"


void protocol_parser_reset(
    protocol_parser_t *parser
)
{
    if (parser == nullptr)
    {
        return;
    }


    parser->state =
        PARSER_WAIT_SOF1;

    parser->payload_index = 0;

    parser->crc_calc =
        0xFFFF;

    parser->crc_received =
        0;

    memset(
        &parser->frame,
        0,
        sizeof(parser->frame)
    );
}


void protocol_parser_init(
    protocol_parser_t *parser
)
{
    protocol_parser_reset(
        parser
    );
}


bool protocol_parser_input(
    protocol_parser_t *parser,
    uint8_t byte,
    protocol_frame_t *output
)
{
    if (
        parser == nullptr ||
        output == nullptr
    )
    {
        return false;
    }


    switch (parser->state)
    {
        // ====================================================
        // SOF1
        // ====================================================

        case PARSER_WAIT_SOF1:
        {
            if (
                byte ==
                PROTOCOL_SOF1
            )
            {
                parser->state =
                    PARSER_WAIT_SOF2;
            }

            break;
        }


        // ====================================================
        // SOF2
        // ====================================================

        case PARSER_WAIT_SOF2:
        {
            if (
                byte ==
                PROTOCOL_SOF2
            )
            {
                parser->crc_calc =
                    0xFFFF;

                parser->state =
                    PARSER_WAIT_LEN;
            }

            else if (
                byte ==
                PROTOCOL_SOF1
            )
            {
                parser->state =
                    PARSER_WAIT_SOF2;
            }

            else
            {
                protocol_parser_reset(
                    parser
                );
            }

            break;
        }


        // ====================================================
        // LENGTH
        // ====================================================

        case PARSER_WAIT_LEN:
        {
            if (
                byte >
                PROTOCOL_MAX_PAYLOAD
            )
            {
                protocol_parser_reset(
                    parser
                );

                break;
            }


            parser->frame.length =
                byte;


            parser->crc_calc =
                protocol_crc16_update(
                    parser->crc_calc,
                    byte
                );


            parser->state =
                PARSER_WAIT_RAILING;

            break;
        }


        // ====================================================
        // RAILING
        // ====================================================

        case PARSER_WAIT_RAILING:
        {
            parser->frame.railing_id =
                byte;


            parser->crc_calc =
                protocol_crc16_update(
                    parser->crc_calc,
                    byte
                );


            parser->state =
                PARSER_WAIT_SRC;

            break;
        }


        // ====================================================
        // SRC
        // ====================================================

        case PARSER_WAIT_SRC:
        {
            parser->frame.src =
                byte;


            parser->crc_calc =
                protocol_crc16_update(
                    parser->crc_calc,
                    byte
                );


            parser->state =
                PARSER_WAIT_DST;

            break;
        }


        // ====================================================
        // DST
        // ====================================================

        case PARSER_WAIT_DST:
        {
            parser->frame.dst =
                byte;


            parser->crc_calc =
                protocol_crc16_update(
                    parser->crc_calc,
                    byte
                );


            parser->state =
                PARSER_WAIT_SERVICE;

            break;
        }


        // ====================================================
        // SERVICE
        // ====================================================

        case PARSER_WAIT_SERVICE:
        {
            parser->frame.service =
                byte;


            parser->crc_calc =
                protocol_crc16_update(
                    parser->crc_calc,
                    byte
                );


            parser->state =
                PARSER_WAIT_CMD;

            break;
        }


        // ====================================================
        // CMD
        // ====================================================

        case PARSER_WAIT_CMD:
        {
            parser->frame.command =
                byte;


            parser->crc_calc =
                protocol_crc16_update(
                    parser->crc_calc,
                    byte
                );


            if (
                parser->frame.length == 0
            )
            {
                parser->state =
                    PARSER_WAIT_CRC_HIGH;
            }
            else
            {
                parser->payload_index =
                    0;

                parser->state =
                    PARSER_WAIT_PAYLOAD;
            }

            break;
        }


        // ====================================================
        // PAYLOAD
        // ====================================================

        case PARSER_WAIT_PAYLOAD:
        {
            parser->frame.payload[
                parser->payload_index
            ] = byte;


            parser->payload_index++;


            parser->crc_calc =
                protocol_crc16_update(
                    parser->crc_calc,
                    byte
                );


            if (
                parser->payload_index >=
                parser->frame.length
            )
            {
                parser->state =
                    PARSER_WAIT_CRC_HIGH;
            }

            break;
        }


        // ====================================================
        // CRC HIGH
        // ====================================================

        case PARSER_WAIT_CRC_HIGH:
        {
            parser->crc_received =
                ((uint16_t)byte << 8);


            parser->state =
                PARSER_WAIT_CRC_LOW;

            break;
        }


        // ====================================================
        // CRC LOW
        // ====================================================

        case PARSER_WAIT_CRC_LOW:
        {
            parser->crc_received |=
                byte;


            if (
                parser->crc_received ==
                parser->crc_calc
            )
            {
                memcpy(
                    output,
                    &parser->frame,
                    sizeof(protocol_frame_t)
                );


                protocol_parser_reset(
                    parser
                );


                return true;
            }


            Serial.printf(
                "[PROTO] CRC ERROR "
                "RX=%04X CALC=%04X\n",

                parser->crc_received,
                parser->crc_calc
            );


            protocol_parser_reset(
                parser
            );

            break;
        }


        default:
        {
            protocol_parser_reset(
                parser
            );

            break;
        }
    }


    return false;
}