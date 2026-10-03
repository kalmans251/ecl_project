#include "protocol_parser.h"

#include <string.h>


static void parser_reset(
    protocol_parser_t *parser
)
{
    parser->index =
        0;
}


void protocol_parser_init(
    protocol_parser_t *parser
)
{
    if (
        parser ==
        NULL
    )
    {
        return;
    }


    memset(
        parser,
        0,
        sizeof(*parser)
    );
}


bool protocol_parser_feed(
    protocol_parser_t *parser,
    uint8_t byte,
    protocol_frame_t *out_frame
)
{
    if (
        parser == NULL ||
        out_frame == NULL
    )
    {
        return false;
    }


    /* ========================================================
     * SOF1
     * ======================================================== */

    if (
        parser->index ==
        0
    )
    {
        if (
            byte ==
            PROTOCOL_SOF1
        )
        {
            parser->buffer[0] =
                byte;

            parser->index =
                1;
        }


        return false;
    }


    /* ========================================================
     * SOF2
     * ======================================================== */

    if (
        parser->index ==
        1
    )
    {
        if (
            byte ==
            PROTOCOL_SOF2
        )
        {
            parser->buffer[1] =
                byte;

            parser->index =
                2;
        }
        else if (
            byte ==
            PROTOCOL_SOF1
        )
        {
            parser->buffer[0] =
                byte;

            parser->index =
                1;
        }
        else
        {
            parser_reset(
                parser
            );
        }


        return false;
    }


    if (
        parser->index >=
        sizeof(parser->buffer)
    )
    {
        parser_reset(
            parser
        );

        return false;
    }


    parser->buffer[
        parser->index++
    ] =
        byte;


    /* ========================================================
     * LEN CHECK
     * ======================================================== */

    if (
        parser->index ==
        3
    )
    {
        if (
            parser->buffer[2] >
            PROTOCOL_MAX_PAYLOAD
        )
        {
            parser_reset(
                parser
            );

            return false;
        }
    }


    if (
        parser->index >=
        3
    )
    {
        size_t expected_len =
            10 +
            parser->buffer[2];


        if (
            parser->index ==
            expected_len
        )
        {
            bool ok =
                protocol_decode(
                    parser->buffer,
                    expected_len,
                    out_frame
                );


            parser_reset(
                parser
            );


            return ok;
        }


        if (
            parser->index >
            expected_len
        )
        {
            parser_reset(
                parser
            );
        }
    }


    return false;
}