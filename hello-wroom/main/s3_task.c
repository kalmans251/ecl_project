#include "s3_task.h"

#include "protocol_parser.h"
#include "router.h"
#include "s3_ble.h"

#include "esp_log.h"

#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/stream_buffer.h"
#include "freertos/task.h"


static const char *TAG =
    "S3_TASK";


static QueueHandle_t
s_tx_queue =
    NULL;


static StreamBufferHandle_t
s_rx_stream =
    NULL;


/* ============================================================
 * TX ENQUEUE
 * ============================================================ */

bool s3_task_enqueue_tx(
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
 * BLE CALLBACK -> STREAM BUFFER
 * ============================================================ */

void s3_task_on_ble_rx(
    const uint8_t *data,
    size_t len
)
{
    if (
        s_rx_stream == NULL ||
        data == NULL ||
        len == 0
    )
    {
        return;
    }


    xStreamBufferSend(
        s_rx_stream,
        data,
        len,
        0
    );
}


/* ============================================================
 * RX TASK
 * ============================================================ */

static void s3_rx_task(
    void *arg
)
{
    (void)arg;


    protocol_parser_t parser;


    protocol_parser_init(
        &parser
    );


    uint8_t temp[
        128
    ];


    while (1)
    {
        size_t len =
            xStreamBufferReceive(
                s_rx_stream,

                temp,

                sizeof(temp),

                portMAX_DELAY
            );


        for (
            size_t i = 0;
            i < len;
            i++
        )
        {
            protocol_frame_t frame;


            if (
                protocol_parser_feed(
                    &parser,
                    temp[i],
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

static void s3_tx_task(
    void *arg
)
{
    (void)arg;


    protocol_frame_t frame;


    uint8_t encoded[
        PROTOCOL_MAX_FRAME_SIZE
    ];


    while (1)
    {
        if (
            xQueueReceive(
                s_tx_queue,

                &frame,

                portMAX_DELAY
            )
            !=
            pdTRUE
        )
        {
            continue;
        }


        size_t encoded_len =
            0;


        if (
            !protocol_encode(
                &frame,

                encoded,

                sizeof(encoded),

                &encoded_len
            )
        )
        {
            continue;
        }


        if (
            !s3_ble_send(
                encoded,
                encoded_len
            )
        )
        {
            ESP_LOGW(
                TAG,
                "BLE TX failed/not ready"
            );
        }
    }
}


/* ============================================================
 * INIT
 * ============================================================ */

bool s3_task_init(void)
{
    if (
        s_tx_queue != NULL ||
        s_rx_stream != NULL
    )
    {
        return true;
    }


    s_tx_queue =
        xQueueCreate(
            16,
            sizeof(protocol_frame_t)
        );


    s_rx_stream =
        xStreamBufferCreate(
            2048,
            1
        );


    if (
        s_tx_queue == NULL ||
        s_rx_stream == NULL
    )
    {
        return false;
    }


    if (
        xTaskCreate(
            s3_rx_task,

            "s3_rx",

            4096,

            NULL,

            13,

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
            s3_tx_task,

            "s3_tx",

            4096,

            NULL,

            13,

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
        "S3 tasks started"
    );


    return true;
}