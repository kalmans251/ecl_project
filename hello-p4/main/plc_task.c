#include "board_config.h"

#include "plc_uart.h"
#include "plc_task.h"

#include "protocol.h"
#include "protocol_parser.h"

#include "router.h"


/* ============================================================
 * PLC RX
 * ============================================================ */

static void handle_plc_frame(
    const protocol_frame_t *frame
)
{
    if (
        frame->railing_id !=
        RAILING_ID
    )
    {
        return;
    }


    xQueueSend(
        router_queue,
        frame,
        portMAX_DELAY
    );
}


/* ============================================================
 * PLC TX
 * ============================================================ */

static void process_plc_tx_queue(void)
{
    protocol_frame_t frame;


    uint8_t tx_buffer[
        PROTOCOL_MAX_FRAME_SIZE
    ];


    while (
        xQueueReceive(
            plc_tx_queue,
            &frame,
            0
        ) == pdTRUE
    )
    {
        int tx_len =
            protocol_encode(
                &frame,
                tx_buffer,
                sizeof(tx_buffer)
            );


        if (tx_len > 0)
        {
            plc_uart_send(
                tx_buffer,
                tx_len
            );
        }
    }
}


/* ============================================================
 * PLC TASK
 * ============================================================ */

void plc_task(void *arg)
{
    uint8_t rx_buffer[256];

    protocol_parser_t parser;

    protocol_frame_t frame;


    protocol_parser_init(
        &parser
    );


    while (1)
    {
        int len =
            plc_uart_receive(
                rx_buffer,
                sizeof(rx_buffer)
            );


        if (len > 0)
        {
            for (
                int i = 0;
                i < len;
                i++
            )
            {
                bool complete =
                    protocol_parser_input(
                        &parser,
                        rx_buffer[i],
                        &frame
                    );


                if (complete)
                {
                    handle_plc_frame(
                        &frame
                    );
                }
            }
        }


        process_plc_tx_queue();
    }
}