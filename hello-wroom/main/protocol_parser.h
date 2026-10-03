#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "protocol.h"


typedef struct
{
    uint8_t buffer[
        PROTOCOL_MAX_FRAME_SIZE
    ];

    size_t index;

} protocol_parser_t;


void protocol_parser_init(
    protocol_parser_t *parser
);


bool protocol_parser_feed(
    protocol_parser_t *parser,
    uint8_t byte,
    protocol_frame_t *out_frame
);