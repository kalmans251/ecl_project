#include "p4_task.h"

#include "p4_uart.h"
#include "protocol_parser.h"
#include "router.h"

#include "esp_log.h"

#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"


static const char *TAG =
    "P4_TASK";


static QueueHandle_t
s_tx_queue =
    NULL;


/* ============================================================
 * TX QUEUE
 * ============================================================ */

bool p4_task_enqueue_tx(
    const protocol_frame_t *frame
)
{
    if (
        s_tx_queue == NULL ||
        frame == NULL
    )
    {
        return false;
    }


    return
        xQueueSend(
            s_tx_queue,
            frame,
            pdMS_TO_TICKS(20)
        )
        ==
        pdTRUE;
}


/* ============================================================
 * RX TASK
 * ============================================================ */

static void p4_rx_task(
    void *arg
)
{
    (void)arg;


    protocol_parser_t parser;


    protocol_parser_init(
        &parser
    );


    uint8_t rx[
        128
    ];


    while (1)
    {
        int len =
            p4_uart_read(
                rx,
                sizeof(rx),
                20
            );


        if (
            len <=
            0
        )
        {
            continue;
        }


        for (
            int i = 0;
            i < len;
            i++
        )
        {
            protocol_frame_t frame;


            if (
                protocol_parser_feed(
                    &parser,
                    rx[i],
                    &frame
                )
            )
            {
                router_enqueue(
                    &frame
                );
            }
        }
    }
}


/* ============================================================
 * TX TASK
 * ============================================================ */

static void p4_tx_task(
    void *arg
)
{
    (void)arg;


    protocol_frame_t frame;


    while (1)
    {
        if (
            xQueueReceive(
                s_tx_queue,
                &frame,
                portMAX_DELAY
            )
            ==
            pdTRUE
        )
        {
            if (
                !p4_uart_send_frame(
                    &frame
                )
            )
            {
                ESP_LOGW(
                    TAG,
                    "TX failed"
                );
            }
        }
    }
}


/* ============================================================
 * INIT
 * ============================================================ */

bool p4_task_init(void)
{
    if (
        s_tx_queue !=
        NULL
    )
    {
        return true;
    }


    s_tx_queue =
        xQueueCreate(
            16,
            sizeof(protocol_frame_t)
        );


    if (
        s_tx_queue ==
        NULL
    )
    {
        return false;
    }


    if (
        xTaskCreate(
            p4_rx_task,

            "p4_rx",

            4096,

            NULL,

            15,

            NULL
        )
        !=
        pdPASS
    )
    {
        return false;
    }


    if (
        xTaskCreate(
            p4_tx_task,

            "p4_tx",

            4096,

            NULL,

            14,

            NULL
        )
        !=
        pdPASS
    )
    {
        return false;
    }


    ESP_LOGI(
        TAG,
        "P4 tasks started"
    );


    return true;
}