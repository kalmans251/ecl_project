#include "router.h"

#include "controller.h"
#include "p4_task.h"
#include "s3_task.h"

#include "esp_log.h"

#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"


static const char *TAG =
    "ROUTER";


static QueueHandle_t
s_router_queue =
    NULL;


/* ============================================================
 * ENQUEUE
 * ============================================================ */

bool router_enqueue(
    const protocol_frame_t *frame
)
{
    if (
        s_router_queue == NULL ||
        frame == NULL
    )
    {
        return false;
    }


    return
        xQueueSend(
            s_router_queue,

            frame,

            pdMS_TO_TICKS(20)
        )
        ==
        pdTRUE;
}


/* ============================================================
 * ROUTER TASK
 * ============================================================ */

static void router_task(
    void *arg
)
{
    (void)arg;


    protocol_frame_t frame;


    while (1)
    {
        if (
            xQueueReceive(
                s_router_queue,
                &frame,
                portMAX_DELAY
            )
            !=
            pdTRUE
        )
        {
            continue;
        }


        switch (
            frame.dst
        )
        {
            /* ================================================
             * WROOM
             * ================================================ */

            case NODE_WROOM:
            {
                if (
                    !controller_enqueue(
                        &frame
                    )
                )
                {
                    ESP_LOGW(
                        TAG,
                        "controller queue full"
                    );
                }

                break;
            }


            /* ================================================
             * S3
             * ================================================ */

            case NODE_S3:
            {
                if (
                    !s3_task_enqueue_tx(
                        &frame
                    )
                )
                {
                    ESP_LOGW(
                        TAG,
                        "S3 queue full"
                    );
                }

                break;
            }


            /* ================================================
             * P4 / PI
             * ================================================ */

            case NODE_P4:
            case NODE_PI:
            {
                if (
                    !p4_task_enqueue_tx(
                        &frame
                    )
                )
                {
                    ESP_LOGW(
                        TAG,
                        "P4 queue full"
                    );
                }

                break;
            }


            default:
            {
                ESP_LOGW(
                    TAG,
                    "Unknown dst=0x%02X",
                    frame.dst
                );

                break;
            }
        }
    }
}


/* ============================================================
 * INIT
 * ============================================================ */

bool router_init(void)
{
    if (
        s_router_queue !=
        NULL
    )
    {
        return true;
    }


    s_router_queue =
        xQueueCreate(
            24,
            sizeof(protocol_frame_t)
        );


    if (
        s_router_queue ==
        NULL
    )
    {
        return false;
    }


    if (
        xTaskCreate(
            router_task,

            "router",

            4096,

            NULL,

            12,

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
        "Router started"
    );


    return true;
}