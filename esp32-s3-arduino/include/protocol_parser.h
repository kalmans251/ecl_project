#pragma once

#include <Arduino.h>

#include "protocol.h"


typedef enum
{
    PARSER_WAIT_SOF1 = 0,
    PARSER_WAIT_SOF2,

    PARSER_WAIT_LEN,
    PARSER_WAIT_RAILING,

    PARSER_WAIT_SRC,
    PARSER_WAIT_DST,

    PARSER_WAIT_SERVICE,
    PARSER_WAIT_CMD,

    PARSER_WAIT_PAYLOAD,

    PARSER_WAIT_CRC_HIGH,
    PARSER_WAIT_CRC_LOW

} protocol_parser_state_t;


typedef struct
{
    protocol_parser_state_t state;

    protocol_frame_t frame;

    uint8_t payload_index;

    uint16_t crc_calc;
    uint16_t crc_received;

} protocol_parser_t;


// ============================================================

void protocol_parser_init(
    protocol_parser_t *parser
);


void protocol_parser_reset(
    protocol_parser_t *parser
);


/*
 * return true:
 * 완전한 정상 frame 하나 생성
 *
 * return false:
 * 아직 frame 미완성 또는 CRC 오류
 */
bool protocol_parser_input(
    protocol_parser_t *parser,
    uint8_t byte,
    protocol_frame_t *output
);