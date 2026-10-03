#include "controller.h"

#include <string.h>

#include "board_config.h"

#include "music_player.h"

#include "router.h"
#include "sd_card.h"

#include "esp_log.h"

#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"


static const char *TAG =
    "CONTROLLER";


static QueueHandle_t
s_controller_queue =
    NULL;


/* ============================================================
 * TEMPORARY MUSIC
 *
 * 다음 단계에서
 * 연령대 group / catalog 방식으로 교체.
 * ============================================================ */

#define TEMP_MUSIC_PATH \
    "/sdcard/music/20/DOHKYU~1.MP3"


/* ============================================================
 * ENQUEUE
 * ============================================================ */

bool controller_enqueue(
    const protocol_frame_t *frame
)
{
    if (
        s_controller_queue == NULL ||
        frame == NULL
    )
    {
        return false;
    }


    return
        xQueueSend(
            s_controller_queue,

            frame,

            pdMS_TO_TICKS(
                20
            )
        )
        ==
        pdTRUE;
}


/* ============================================================
 * REPLY
 * ============================================================ */

static void send_reply(
    const protocol_frame_t *request,

    uint8_t cmd,

    const uint8_t *payload,

    uint8_t payload_len
)
{
    protocol_frame_t response;


    protocol_frame_init(
        &response,

        request->railing_id,

        NODE_WROOM,

        request->src,

        request->service,

        cmd
    );


    if (
        payload != NULL &&
        payload_len > 0
    )
    {
        if (
            payload_len >
            PROTOCOL_MAX_PAYLOAD
        )
        {
            payload_len =
                PROTOCOL_MAX_PAYLOAD;
        }


        memcpy(
            response.payload,

            payload,

            payload_len
        );


        response.payload_len =
            payload_len;
    }


    router_enqueue(
        &response
    );
}


/* ============================================================
 * SYSTEM
 * ============================================================ */

static void handle_system(
    const protocol_frame_t *frame
)
{
    switch (
        frame->cmd
    )
    {
        case CMD_PING:
        {
            send_reply(
                frame,

                CMD_PONG,

                NULL,

                0
            );


            break;
        }


        case CMD_ECHO:
        {
            send_reply(
                frame,

                CMD_ECHO_RESPONSE,

                frame->payload,

                frame->payload_len
            );


            break;
        }


        case CMD_STATUS_REQUEST:
        {
            uint8_t status[] =
            {
                0x01,

                sd_card_is_mounted()
                    ?
                    0x01
                    :
                    0x00,

                (uint8_t)
                music_player_get_state(),

                RAILING_ID
            };


            send_reply(
                frame,

                CMD_STATUS_RESPONSE,

                status,

                sizeof(status)
            );


            break;
        }


        default:
        {
            break;
        }
    }
}


/* ============================================================
 * MUSIC
 * ============================================================ */

static void handle_music(
    const protocol_frame_t *frame
)
{
    switch (
        frame->cmd
    )
    {
        /* ====================================================
         * START
         * ==================================================== */

        case CMD_START:
        {
            ESP_LOGI(
                TAG,
                "MUSIC START"
            );


            if (
                !music_player_start(
                    TEMP_MUSIC_PATH
                )
            )
            {
                ESP_LOGE(
                    TAG,
                    "Music START failed"
                );
            }


            break;
        }


        /* ====================================================
         * STOP
         * ==================================================== */

        case CMD_STOP:
        {
            ESP_LOGI(
                TAG,
                "MUSIC STOP"
            );


            music_player_stop();


            break;
        }


        /* ====================================================
         * PAUSE
         * ==================================================== */

        case CMD_PAUSE:
        {
            ESP_LOGI(
                TAG,
                "MUSIC PAUSE"
            );


            music_player_pause();


            break;
        }


        /* ====================================================
         * RESUME
         * ==================================================== */

        case CMD_RESUME:
        {
            ESP_LOGI(
                TAG,
                "MUSIC RESUME"
            );


            music_player_resume();


            break;
        }


        default:
        {
            ESP_LOGW(
                TAG,
                "Unknown MUSIC command 0x%02X",
                frame->cmd
            );


            break;
        }
    }
}


/* ============================================================
 * SD
 * ============================================================ */

static void handle_sd(
    const protocol_frame_t *frame
)
{
    ESP_LOGI(
        TAG,
        "SD cmd=0x%02X",
        frame->cmd
    );
}


/* ============================================================
 * TASK
 * ============================================================ */

static void controller_task(
    void *arg
)
{
    (void)arg;


    protocol_frame_t frame;


    while (1)
    {
        if (
            xQueueReceive(
                s_controller_queue,

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
            frame.service
        )
        {
            case SERVICE_SYSTEM:
            {
                handle_system(
                    &frame
                );


                break;
            }


            case SERVICE_MUSIC:
            {
                handle_music(
                    &frame
                );


                break;
            }


            case SERVICE_SD:
            {
                handle_sd(
                    &frame
                );


                break;
            }


            default:
            {
                ESP_LOGI(
                    TAG,
                    "service=0x%02X cmd=0x%02X",
                    frame.service,
                    frame.cmd
                );


                break;
            }
        }
    }
}


/* ============================================================
 * INIT
 * ============================================================ */

bool controller_init(void)
{
    if (
        s_controller_queue !=
        NULL
    )
    {
        return true;
    }


    s_controller_queue =
        xQueueCreate(
            16,

            sizeof(protocol_frame_t)
        );


    if (
        s_controller_queue ==
        NULL
    )
    {
        return false;
    }


    if (
        xTaskCreate(
            controller_task,

            "controller",

            4096,

            NULL,

            10,

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
        "Controller started"
    );


    return true;
}