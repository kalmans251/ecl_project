#include <stdio.h>

#include "router.h"
#include "call_manager.h"
#include "event_outbox.h"
#include "radar_cache.h"


QueueHandle_t router_queue = NULL;

QueueHandle_t plc_tx_queue = NULL;

QueueHandle_t wroom_tx_queue = NULL;

QueueHandle_t p4_controller_queue = NULL;


/* ============================================================
 * INIT
 * ============================================================ */

void router_init(void)
{
    router_queue =
        xQueueCreate(
            20,
            sizeof(protocol_frame_t)
        );


    plc_tx_queue =
        xQueueCreate(
            20,
            sizeof(protocol_frame_t)
        );


    wroom_tx_queue =
        xQueueCreate(
            20,
            sizeof(protocol_frame_t)
        );


    p4_controller_queue =
        xQueueCreate(
            20,
            sizeof(protocol_frame_t)
        );


    if (
        router_queue == NULL ||
        plc_tx_queue == NULL ||
        wroom_tx_queue == NULL ||
        p4_controller_queue == NULL
    )
    {
        printf(
            "[ROUTER] Queue create FAILED\n"
        );
    }
}


/* ============================================================
 * ROUTER TASK
 * ============================================================ */

void router_task(void *arg)
{
    protocol_frame_t frame;


    while (1)
    {
        if (
            xQueueReceive(
                router_queue,
                &frame,
                portMAX_DELAY
            ) != pdTRUE
        )
        {
            continue;
        }


        if (!call_manager_voice_allowed(&frame)) continue;
        if (radar_cache_capture(&frame)) continue;
        protocol_frame_t radar_reply = {0};
        if (radar_cache_reply(&frame, &radar_reply)) {
            if (radar_reply.length) xQueueSend(plc_tx_queue, &radar_reply, pdMS_TO_TICKS(20));
            continue;
        }
        switch (frame.dst)
        {
            /* ================================================
             * PI
             * ================================================ */

            case NODE_PI:
            {
                if (event_outbox_capture(&frame)) break;
                xQueueSend(
                    plc_tx_queue,
                    &frame,
                    portMAX_DELAY
                );

                break;
            }


            /* ================================================
             * P4
             * ================================================ */

            case NODE_P4:
            {
                xQueueSend(
                    p4_controller_queue,
                    &frame,
                    portMAX_DELAY
                );

                break;
            }


            /* ================================================
             * WROOM
             * ================================================ */

            case NODE_WROOM:
            {
                xQueueSend(
                    wroom_tx_queue,
                    &frame,
                    portMAX_DELAY
                );

                break;
            }


            /* ================================================
             * S3
             *
             * S3는 WROOM 뒤에 있음
             * ================================================ */

            case NODE_S3:
            {
                xQueueSend(
                    wroom_tx_queue,
                    &frame,
                    portMAX_DELAY
                );

                break;
            }


            default:
            {
                break;
            }
        }
    }
}