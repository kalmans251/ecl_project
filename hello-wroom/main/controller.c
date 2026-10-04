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

#include "playlist_manager.h"

#include "sd_manager.h"

static const char *TAG =
    "CONTROLLER";


static QueueHandle_t
s_controller_queue =
    NULL;




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
                !sd_manager_is_ready()
            )
            {
                ESP_LOGW(
                    TAG,
                    "MUSIC START rejected: SD not ready"
                );


                break;
            }

            if (
                !playlist_manager_start()
            )
            {
                ESP_LOGE(
                    TAG,
                    "Playlist START failed"
                );
            }


            break;
        }


        /* ====================================================
         * NEXT
         * ==================================================== */

        case CMD_NEXT:
        {
            ESP_LOGI(
                TAG,
                "MUSIC NEXT"
            );

            if (
                !sd_manager_is_ready()
            )
            {
                ESP_LOGW(
                    TAG,
                    "MUSIC NEXT rejected: SD not ready"
                );


                break;
            }

            if (
                !playlist_manager_next()
            )
            {
                ESP_LOGE(
                    TAG,
                    "Playlist NEXT failed"
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


        /* ====================================================
         * SET
         *
         * payload[0] = MUSIC_SET_*
         * payload[1] = value
         * ==================================================== */

        case CMD_SET:
        {
            if (
                frame->payload_len <
                2
            )
            {
                ESP_LOGW(
                    TAG,
                    "MUSIC SET payload too short"
                );


                break;
            }


            uint8_t type =
                frame->payload[0];


            uint8_t value =
                frame->payload[1];


            if (
                type ==
                MUSIC_SET_PLAY_MODE
            )
            {
                if (
                    !playlist_manager_set_mode(
                        (music_play_mode_t)
                        value
                    )
                )
                {
                    ESP_LOGW(
                        TAG,
                        "Invalid play mode=%u",
                        value
                    );
                }
            }
            else if (
                type ==
                MUSIC_SET_GROUP
            )
            {
                if (
                    !playlist_manager_set_group(
                        (music_group_t)
                        value
                    )
                )
                {
                    ESP_LOGW(
                        TAG,
                        "Invalid music group=%u",
                        value
                    );
                }
            }


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
 * WRITE U16 BE
 * ============================================================ */

static void write_u16_be(
    uint8_t *dst,
    uint16_t value
)
{
    dst[0] =
        (uint8_t)(
            value >> 8
        );

    dst[1] =
        (uint8_t)(
            value
        );
}


/* ============================================================
 * WRITE U32 BE
 * ============================================================ */

static void write_u32_be(
    uint8_t *dst,
    uint32_t value
)
{
    dst[0] =
        (uint8_t)(
            value >> 24
        );

    dst[1] =
        (uint8_t)(
            value >> 16
        );

    dst[2] =
        (uint8_t)(
            value >> 8
        );

    dst[3] =
        (uint8_t)(
            value
        );
}


/* ============================================================
 * SD
 * ============================================================ */

static void handle_sd(
    const protocol_frame_t *frame
)
{
    switch (
        frame->cmd
    )
    {
        /* ====================================================
         * STATUS REQUEST
         *
         * RESPONSE:
         *
         * [0]      SD READY
         * [1..4]   catalog_version
         * [5..6]   total
         * [7..8]   default
         * [9..10]  10s
         * [11..12] 20s
         * [13..14] 30s
         * [15..16] 40s
         * ==================================================== */

        case CMD_STATUS_REQUEST:
        {
            uint8_t payload[
                17
            ];


            memset(
                payload,
                0,
                sizeof(payload)
            );


            bool ready =
                sd_manager_is_ready();


            payload[0] =
                ready
                    ?
                    1
                    :
                    0;


            /*
             * SD가 준비되지 않은 경우
             * version/count는 모두 0으로 응답.
             */
            if (
                !ready
            )
            {
                send_reply(
                    frame,
                    CMD_STATUS_RESPONSE,
                    payload,
                    sizeof(payload)
                );


                ESP_LOGI(
                    TAG,
                    "SD STATUS ready=0"
                );


                break;
            }


            uint32_t version =
                playlist_manager_get_catalog_version();


            uint16_t total =
                playlist_manager_get_total_track_count();


            uint16_t count_default =
                playlist_manager_get_group_track_count(
                    MUSIC_GROUP_DEFAULT
                );


            uint16_t count_10 =
                playlist_manager_get_group_track_count(
                    MUSIC_GROUP_10S
                );


            uint16_t count_20 =
                playlist_manager_get_group_track_count(
                    MUSIC_GROUP_20S
                );


            uint16_t count_30 =
                playlist_manager_get_group_track_count(
                    MUSIC_GROUP_30S
                );


            uint16_t count_40 =
                playlist_manager_get_group_track_count(
                    MUSIC_GROUP_40S
                );


            write_u32_be(
                &payload[1],
                version
            );


            write_u16_be(
                &payload[5],
                total
            );


            write_u16_be(
                &payload[7],
                count_default
            );


            write_u16_be(
                &payload[9],
                count_10
            );


            write_u16_be(
                &payload[11],
                count_20
            );


            write_u16_be(
                &payload[13],
                count_30
            );


            write_u16_be(
                &payload[15],
                count_40
            );


            send_reply(
                frame,
                CMD_STATUS_RESPONSE,
                payload,
                sizeof(payload)
            );


            ESP_LOGI(
                TAG,
                "SD STATUS ready=1 version=0x%08lX total=%u",
                (unsigned long)version,
                (unsigned)total
            );


            break;
        }


        /* ====================================================
         * DATA
         * ==================================================== */

        case CMD_DATA:
        {
            if (
                frame->payload_len <
                1
            )
            {
                ESP_LOGW(
                    TAG,
                    "SD DATA payload empty"
                );


                break;
            }


            uint8_t type =
                frame->payload[0];


            /* =================================================
             * TRACK REQUEST
             *
             * REQUEST:
             *
             * [0]     SD_DATA_TRACK_REQUEST
             * [1]     group
             * [2..3]  index
             * ================================================= */

            if (
                type ==
                    SD_DATA_TRACK_REQUEST
            )
            {
                if (
                    frame->payload_len <
                    4
                )
                {
                    ESP_LOGW(
                        TAG,
                        "SD track request too short"
                    );


                    break;
                }


                if (
                    !sd_manager_is_ready()
                )
                {
                    ESP_LOGW(
                        TAG,
                        "SD track request rejected: SD not ready"
                    );


                    break;
                }


                music_group_t group =
                    (music_group_t)
                    frame->payload[1];


                uint16_t index =
                    (
                        ((uint16_t)
                        frame->payload[2])
                        <<
                        8
                    )
                    |
                    frame->payload[3];


                char filename[
                    96
                ];


                if (
                    !playlist_manager_get_track_filename(
                        group,
                        index,
                        filename,
                        sizeof(filename)
                    )
                )
                {
                    ESP_LOGW(
                        TAG,
                        "Track not found group=%u index=%u",
                        (unsigned)group,
                        (unsigned)index
                    );


                    break;
                }


                size_t filename_len =
                    strlen(
                        filename
                    );


                /*
                 * 9 bytes metadata + filename
                 */
                if (
                    9 +
                    filename_len >
                        PROTOCOL_MAX_PAYLOAD
                )
                {
                    ESP_LOGW(
                        TAG,
                        "Track filename too long"
                    );


                    break;
                }


                uint8_t payload[
                    PROTOCOL_MAX_PAYLOAD
                ];


                uint32_t version =
                    playlist_manager_get_catalog_version();


                payload[0] =
                    SD_DATA_TRACK_RESPONSE;


                payload[1] =
                    (uint8_t)group;


                write_u16_be(
                    &payload[2],
                    index
                );


                write_u32_be(
                    &payload[4],
                    version
                );


                payload[8] =
                    (uint8_t)
                    filename_len;


                memcpy(
                    &payload[9],
                    filename,
                    filename_len
                );


                send_reply(
                    frame,
                    CMD_DATA,
                    payload,
                    (uint8_t)(
                        9 +
                        filename_len
                    )
                );


                ESP_LOGI(
                    TAG,
                    "TRACK RESP group=%u index=%u file=%s",
                    (unsigned)group,
                    (unsigned)index,
                    filename
                );
            }
            else
            {
                ESP_LOGW(
                    TAG,
                    "Unknown SD DATA type=0x%02X",
                    type
                );
            }


            break;
        }


        default:
        {
            ESP_LOGW(
                TAG,
                "Unknown SD command 0x%02X",
                frame->cmd
            );


            break;
        }
    }
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