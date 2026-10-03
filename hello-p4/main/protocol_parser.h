#pragma once

#include <stdint.h>
#include <stdbool.h>

#include "protocol.h"


typedef enum
{
    PARSER_WAIT_SOF1 = 0,

    PARSER_WAIT_SOF2,

    PARSER_WAIT_LEN,

    PARSER_WAIT_RAILING_ID,

    PARSER_WAIT_SRC,

    PARSER_WAIT_DST,

    PARSER_WAIT_SERVICE,

    PARSER_WAIT_CMD,

    PARSER_WAIT_PAYLOAD,

    PARSER_WAIT_CRC_HIGH,

    PARSER_WAIT_CRC_LOW

} parser_state_t;


typedef struct
{
    parser_state_t state;

    protocol_frame_t frame;

    uint8_t payload_index;


    /* CRC 계산값 */

    uint16_t crc_calc;


    /* 수신 CRC */

    uint16_t crc_received;


} protocol_parser_t;


void protocol_parser_init(
    protocol_parser_t *parser
);


bool protocol_parser_input(
    protocol_parser_t *parser,
    uint8_t byte,
    protocol_frame_t *output_frame
);