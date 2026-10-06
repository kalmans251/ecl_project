#include "music_player.h"
#include "music_eq.h"

#include <fcntl.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include <unistd.h>

#include "audio_output.h"
#include "board_config.h"

#include "protocol.h"
#include "router.h"

#include "sd_card.h"

#include "esp_attr.h"
#include "esp_log.h"

#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"


/* ============================================================
 * MINIMP3
 *
 * 프로젝트 전체에서
 * MINIMP3_IMPLEMENTATION은 이 파일 한 곳에서만 정의.
 * ============================================================ */

#define MINIMP3_ONLY_MP3
#define MINIMP3_NO_SIMD
#define MINIMP3_IMPLEMENTATION

#include "minimp3.h"


static const char *TAG =
    "MUSIC_PLAYER";


/* ============================================================
 * CONFIG
 * ============================================================ */

#define MUSIC_TASK_STACK_SIZE \
    (32 * 1024)

#define MUSIC_TASK_PRIORITY \
    8

#define MUSIC_COMMAND_QUEUE_LENGTH \
    8

#define MUSIC_PATH_MAX \
    256

#define MP3_INPUT_BUFFER_SIZE \
    (16 * 1024)

#define SD_READ_SIZE \
    512


/* ============================================================
 * PLAYER COMMAND
 * ============================================================ */

typedef enum
{
    PLAYER_CMD_START = 1,

    PLAYER_CMD_STOP,

    PLAYER_CMD_PAUSE,

    PLAYER_CMD_RESUME,

} player_command_type_t;


typedef struct
{
    player_command_type_t type;
    bool confirm_stop;
    uint8_t confirm_rail;
    uint8_t request_id[4];

    char path[
        MUSIC_PATH_MAX
    ];

} player_command_t;


static player_command_t s_stop_confirmation;

static void confirm_stopped(const player_command_t *command)
{
    if (!command->confirm_stop) return;
    protocol_frame_t result;
    protocol_frame_init(&result, command->confirm_rail, NODE_WROOM, NODE_P4,
                        SERVICE_MUSIC, CMD_APPLY_RESULT);
    result.payload_len = 7;
    memcpy(result.payload, command->request_id, 4);
    result.payload[4] = CMD_STOP;
    result.payload[5] = 0; // applied after cleanup, or already idle
    result.payload[6] = MUSIC_PLAYER_IDLE;
    router_enqueue(&result);
}

/* ============================================================
 * PLAY RESULT
 * ============================================================ */

typedef enum
{
    PLAY_RESULT_FINISHED = 0,

    PLAY_RESULT_STOPPED,

    PLAY_RESULT_RESTART,

    PLAY_RESULT_ERROR,

} play_result_t;


/* ============================================================
 * STATIC
 * ============================================================ */

static QueueHandle_t
s_command_queue =
    NULL;


static TaskHandle_t
s_music_task =
    NULL;


static volatile music_player_state_t
s_state =
    MUSIC_PLAYER_IDLE;


/* ============================================================
 * MP3 BUFFERS
 * ============================================================ */

DMA_ATTR
static uint8_t
s_sd_read_buffer[
    SD_READ_SIZE
];


static uint8_t
s_mp3_buffer[
    MP3_INPUT_BUFFER_SIZE
];


static mp3d_sample_t
s_decode_pcm[
    MINIMP3_MAX_SAMPLES_PER_FRAME
];


static int16_t
s_stereo_pcm[
    MINIMP3_MAX_SAMPLES_PER_FRAME
];


static mp3dec_t
s_decoder;


/* ============================================================
 * COPY PATH
 * ============================================================ */

static bool copy_path(
    char *dst,
    size_t dst_size,
    const char *src
)
{
    if (
        dst == NULL ||
        src == NULL ||
        dst_size == 0
    )
    {
        return false;
    }


    size_t len =
        strlen(
            src
        );


    if (
        len + 1 >
        dst_size
    )
    {
        return false;
    }


    memcpy(
        dst,
        src,
        len
    );


    dst[len] =
        '\0';


    return true;
}


/* ============================================================
 * SEND MUSIC EVENT -> P4
 * ============================================================ */

static void send_music_event(
    music_event_t event
)
{
    if (event == MUSIC_EVENT_PAUSED || event == MUSIC_EVENT_STOPPED
            || event == MUSIC_EVENT_FINISHED || event == MUSIC_EVENT_ERROR)
        music_eq_clear();
    else if (event == MUSIC_EVENT_STARTED || event == MUSIC_EVENT_RESUMED)
        music_eq_reset();

    protocol_frame_t frame;


    protocol_frame_init(
        &frame,

        RAILING_ID,

        NODE_WROOM,

        NODE_P4,

        SERVICE_MUSIC,

        CMD_DATA
    );


    frame.payload_len =
        1;


    frame.payload[0] =
        (uint8_t)event;


    if (
        !router_enqueue(
            &frame
        )
    )
    {
        ESP_LOGW(
            TAG,
            "Music event queue failed: 0x%02X",
            event
        );
    }
}


/* ============================================================
 * ID3 SKIP
 * ============================================================ */

static bool skip_id3v2(
    int fd
)
{
    uint8_t header[
        10
    ];


    ssize_t n =
        read(
            fd,
            header,
            sizeof(header)
        );


    if (
        n !=
        sizeof(header)
    )
    {
        lseek(
            fd,
            0,
            SEEK_SET
        );


        return true;
    }


    if (
        header[0] != 'I' ||
        header[1] != 'D' ||
        header[2] != '3'
    )
    {
        lseek(
            fd,
            0,
            SEEK_SET
        );


        return true;
    }


    uint32_t tag_size =
        ((uint32_t)(header[6] & 0x7F) << 21)
        |
        ((uint32_t)(header[7] & 0x7F) << 14)
        |
        ((uint32_t)(header[8] & 0x7F) << 7)
        |
        ((uint32_t)(header[9] & 0x7F));


    uint32_t total =
        10 +
        tag_size;


    /*
     * ID3 footer
     */
    if (
        header[5] &
        0x10
    )
    {
        total +=
            10;
    }


    ESP_LOGI(
        TAG,
        "ID3 skip = %lu bytes",
        (unsigned long)total
    );


    return
        lseek(
            fd,
            (off_t)total,
            SEEK_SET
        )
        >=
        0;
}


/* ============================================================
 * CHECK CONTROL COMMANDS
 * ============================================================ */

static void process_control_commands(
    bool *paused,
    bool *stop_requested,
    bool *restart_requested,
    char *restart_path,
    size_t restart_path_size
)
{
    player_command_t command;


    while (
        xQueueReceive(
            s_command_queue,
            &command,
            0
        )
        ==
        pdTRUE
    )
    {
        switch (
            command.type
        )
        {
            /* ================================================
             * STOP
             * ================================================ */

            case PLAYER_CMD_STOP:
            {
                s_stop_confirmation = command;
                *stop_requested =
                    true;


                return;
            }


            /* ================================================
             * PAUSE
             * ================================================ */

            case PLAYER_CMD_PAUSE:
            {
                if (
                    !*paused &&
                    s_state ==
                    MUSIC_PLAYER_PLAYING
                )
                {
                    *paused =
                        true;


                    s_state =
                        MUSIC_PLAYER_PAUSED;


                    ESP_LOGI(
                        TAG,
                        "PAUSE"
                    );


                    send_music_event(
                        MUSIC_EVENT_PAUSED
                    );
                }


                break;
            }


            /* ================================================
             * RESUME
             * ================================================ */

            case PLAYER_CMD_RESUME:
            {
                if (
                    *paused
                )
                {
                    *paused =
                        false;


                    s_state =
                        MUSIC_PLAYER_PLAYING;


                    ESP_LOGI(
                        TAG,
                        "RESUME"
                    );


                    send_music_event(
                        MUSIC_EVENT_RESUMED
                    );
                }


                break;
            }


            /* ================================================
             * START WHILE PLAYING
             *
             * 현재 곡 중지 후 새 곡으로 변경.
             * ================================================ */

            case PLAYER_CMD_START:
            {
                if (
                    copy_path(
                        restart_path,
                        restart_path_size,
                        command.path
                    )
                )
                {
                    *restart_requested =
                        true;
                }


                return;
            }


            default:
            {
                break;
            }
        }
    }
}


/* ============================================================
 * PAUSED WAIT
 * ============================================================ */

static void wait_while_paused(
    bool *paused,
    bool *stop_requested,
    bool *restart_requested,
    char *restart_path,
    size_t restart_path_size
)
{
    while (
        *paused &&
        !*stop_requested &&
        !*restart_requested
    )
    {
        player_command_t command;


        if (
            xQueueReceive(
                s_command_queue,
                &command,
                portMAX_DELAY
            )
            !=
            pdTRUE
        )
        {
            continue;
        }


        switch (
            command.type
        )
        {
            case PLAYER_CMD_RESUME:
            {
                *paused =
                    false;


                s_state =
                    MUSIC_PLAYER_PLAYING;


                ESP_LOGI(
                    TAG,
                    "RESUME"
                );


                send_music_event(
                    MUSIC_EVENT_RESUMED
                );


                break;
            }


            case PLAYER_CMD_STOP:
            {
                s_stop_confirmation = command;
                *stop_requested =
                    true;


                return;
            }


            case PLAYER_CMD_START:
            {
                if (
                    copy_path(
                        restart_path,
                        restart_path_size,
                        command.path
                    )
                )
                {
                    *restart_requested =
                        true;
                }


                break;
            }


            case PLAYER_CMD_PAUSE:
            default:
            {
                break;
            }
        }
    }
}


/* ============================================================
 * PLAY ONE MP3
 * ============================================================ */

static play_result_t play_mp3_file(
    const char *path,
    char *restart_path,
    size_t restart_path_size
)
{
    if (
        !sd_card_is_mounted()
    )
    {
        ESP_LOGE(
            TAG,
            "SD card not mounted"
        );


        send_music_event(
            MUSIC_EVENT_ERROR
        );


        return PLAY_RESULT_ERROR;
    }


    ESP_LOGI(
        TAG,
        "Opening: %s",
        path
    );


    int fd =
        open(
            path,
            O_RDONLY
        );


    if (
        fd <
        0
    )
    {
        ESP_LOGE(
            TAG,
            "MP3 open failed"
        );


        send_music_event(
            MUSIC_EVENT_ERROR
        );


        return PLAY_RESULT_ERROR;
    }


    if (
        !skip_id3v2(
            fd
        )
    )
    {
        close(
            fd
        );


        send_music_event(
            MUSIC_EVENT_ERROR
        );


        return PLAY_RESULT_ERROR;
    }


    music_eq_reset();

    mp3dec_init(
        &s_decoder
    );


    size_t buffer_len =
        0;


    bool eof =
        false;


    bool paused =
        false;


    bool stop_requested =
        false;


    bool restart_requested =
        false;


    bool playback_started =
        false;


    uint64_t decoded_sample_frames =
        0;


    uint32_t last_second =
        UINT32_MAX;


    restart_path[0] =
        '\0';


    while (1)
    {
        /* ====================================================
         * CONTROL
         * ==================================================== */

        process_control_commands(
            &paused,

            &stop_requested,

            &restart_requested,

            restart_path,

            restart_path_size
        );


        if (
            stop_requested ||
            restart_requested
        )
        {
            break;
        }


        /* ====================================================
         * PAUSE
         * ==================================================== */

        if (
            paused
        )
        {
            wait_while_paused(
                &paused,

                &stop_requested,

                &restart_requested,

                restart_path,

                restart_path_size
            );


            if (
                stop_requested ||
                restart_requested
            )
            {
                break;
            }
        }


        /* ====================================================
         * MP3 BUFFER FILL
         * ==================================================== */

        while (
            !eof
            &&
            buffer_len +
            SD_READ_SIZE
            <=
            sizeof(s_mp3_buffer)
        )
        {
            /*
             * read 중간에도 제어 명령 확인
             */
            process_control_commands(
                &paused,

                &stop_requested,

                &restart_requested,

                restart_path,

                restart_path_size
            );


            if (
                stop_requested ||
                restart_requested ||
                paused
            )
            {
                break;
            }


            ssize_t read_size =
                read(
                    fd,

                    s_sd_read_buffer,

                    SD_READ_SIZE
                );


            if (
                read_size >
                0
            )
            {
                memcpy(
                    &s_mp3_buffer[
                        buffer_len
                    ],

                    s_sd_read_buffer,

                    (size_t)read_size
                );


                buffer_len +=
                    (size_t)read_size;


                if (
                    read_size <
                    SD_READ_SIZE
                )
                {
                    eof =
                        true;


                    break;
                }
            }
            else if (
                read_size ==
                0
            )
            {
                eof =
                    true;


                break;
            }
            else
            {
                ESP_LOGE(
                    TAG,
                    "SD read error"
                );


                close(
                    fd
                );


                audio_output_deinit();


                s_state =
                    MUSIC_PLAYER_IDLE;


                send_music_event(
                    MUSIC_EVENT_ERROR
                );


                return PLAY_RESULT_ERROR;
            }


            if (
                (
                    buffer_len %
                    4096
                )
                ==
                0
            )
            {
                vTaskDelay(
                    1
                );
            }
        }


        if (
            stop_requested ||
            restart_requested
        )
        {
            break;
        }


        if (
            paused
        )
        {
            continue;
        }


        /* ====================================================
         * EOF
         * ==================================================== */

        if (
            buffer_len ==
            0
            &&
            eof
        )
        {
            break;
        }


        /* ====================================================
         * DECODE
         * ==================================================== */

        mp3dec_frame_info_t info =
        {
            0
        };


        int samples =
            mp3dec_decode_frame(
                &s_decoder,

                s_mp3_buffer,

                (int)buffer_len,

                s_decode_pcm,

                &info
            );


        /* ====================================================
         * CONSUME
         * ==================================================== */

        if (
            info.frame_bytes >
            0
        )
        {
            size_t consumed =
                (size_t)
                info.frame_bytes;


            if (
                consumed >
                buffer_len
            )
            {
                close(
                    fd
                );


                audio_output_deinit();


                s_state =
                    MUSIC_PLAYER_IDLE;


                send_music_event(
                    MUSIC_EVENT_ERROR
                );


                return PLAY_RESULT_ERROR;
            }


            size_t remaining =
                buffer_len -
                consumed;


            if (
                remaining >
                0
            )
            {
                memmove(
                    s_mp3_buffer,

                    &s_mp3_buffer[
                        consumed
                    ],

                    remaining
                );
            }


            buffer_len =
                remaining;
        }


        /* ====================================================
         * PCM
         * ==================================================== */

        if (
            samples >
            0
        )
        {
            if (
                info.hz <=
                0
                ||
                (
                    info.channels != 1
                    &&
                    info.channels != 2
                )
            )
            {
                close(
                    fd
                );


                audio_output_deinit();


                s_state =
                    MUSIC_PLAYER_IDLE;


                send_music_event(
                    MUSIC_EVENT_ERROR
                );


                return PLAY_RESULT_ERROR;
            }


            /* ================================================
             * FIRST FRAME
             * ================================================ */

            if (
                !playback_started
            )
            {
                ESP_LOGI(
                    TAG,
                    "MP3 %d Hz / %d ch / %d kbps",
                    info.hz,
                    info.channels,
                    info.bitrate_kbps
                );


                if (
                    !audio_output_init(
                        (uint32_t)info.hz
                    )
                )
                {
                    close(
                        fd
                    );


                    s_state =
                        MUSIC_PLAYER_IDLE;


                    send_music_event(
                        MUSIC_EVENT_ERROR
                    );


                    return PLAY_RESULT_ERROR;
                }


                playback_started =
                    true;


                s_state =
                    MUSIC_PLAYER_PLAYING;


                send_music_event(
                    MUSIC_EVENT_STARTED
                );


                ESP_LOGI(
                    TAG,
                    "STARTED"
                );
            }
            else
            {
                if (
                    !audio_output_set_sample_rate(
                        (uint32_t)info.hz
                    )
                )
                {
                    close(
                        fd
                    );


                    audio_output_deinit();


                    s_state =
                        MUSIC_PLAYER_IDLE;


                    send_music_event(
                        MUSIC_EVENT_ERROR
                    );


                    return PLAY_RESULT_ERROR;
                }
            }


            /* ================================================
             * PCM OUTPUT
             * ================================================ */

            size_t output_samples =
                0;


            const int16_t *output =
                NULL;


            if (
                info.channels ==
                2
            )
            {
                output_samples =
                    (size_t)samples *
                    2;


                output =
                    s_decode_pcm;
            }
            else
            {
                output_samples =
                    (size_t)samples *
                    2;


                for (
                    int i = 0;
                    i < samples;
                    i++
                )
                {
                    s_stereo_pcm[
                        i *
                        2
                    ] =
                        s_decode_pcm[i];


                    s_stereo_pcm[
                        i *
                        2 +
                        1
                    ] =
                        s_decode_pcm[i];
                }


                output =
                    s_stereo_pcm;
            }


            if (
                !audio_output_write(
                    output,
                    output_samples
                )
            )
            {
                close(
                    fd
                );


                audio_output_deinit();


                s_state =
                    MUSIC_PLAYER_IDLE;


                send_music_event(
                    MUSIC_EVENT_ERROR
                );


                return PLAY_RESULT_ERROR;
            }


            music_eq_feed(output, output_samples, info.hz);

            /* ================================================
             * POSITION
             * ================================================ */

            decoded_sample_frames +=
                (uint64_t)samples;


            uint32_t second =
                (uint32_t)(
                    decoded_sample_frames
                    /
                    (uint64_t)info.hz
                );


            if (
                second !=
                last_second
            )
            {
                last_second =
                    second;


                ESP_LOGI(
                    TAG,
                    "Playing %lu sec",
                    (unsigned long)second
                );
            }
        }


        /* ====================================================
         * NO SYNC
         * ==================================================== */

        if (
            samples ==
            0
            &&
            info.frame_bytes ==
            0
        )
        {
            if (
                eof
            )
            {
                break;
            }


            if (
                buffer_len ==
                sizeof(s_mp3_buffer)
            )
            {
                memmove(
                    s_mp3_buffer,

                    &s_mp3_buffer[
                        SD_READ_SIZE
                    ],

                    buffer_len -
                    SD_READ_SIZE
                );


                buffer_len -=
                    SD_READ_SIZE;
            }
        }

        if (samples == 0){
            vTaskDelay(1);
        }

    }


    /* ========================================================
     * CLOSE
     * ======================================================== */

    close(
        fd
    );


    /*
     * 마지막 DMA 데이터 출력 시간을 약간 줌.
     */

    if (
        playback_started &&
        !stop_requested &&
        !restart_requested
    )
    {
        vTaskDelay(
            pdMS_TO_TICKS(
                50
            )
        );
    }


    music_eq_clear();
    audio_output_deinit();


    s_state =
        MUSIC_PLAYER_IDLE;
    confirm_stopped(&s_stop_confirmation);
    memset(&s_stop_confirmation, 0, sizeof(s_stop_confirmation));


    /* ========================================================
     * RESTART
     * ======================================================== */

    if (
        restart_requested
    )
    {
        ESP_LOGI(
            TAG,
            "Restart with another track"
        );


        return PLAY_RESULT_RESTART;
    }


    /* ========================================================
     * STOP
     * ======================================================== */

    if (
        stop_requested
    )
    {
        ESP_LOGI(
            TAG,
            "STOPPED"
        );


        send_music_event(
            MUSIC_EVENT_STOPPED
        );


        return PLAY_RESULT_STOPPED;
    }


    /* ========================================================
     * NATURAL FINISH
     * ======================================================== */

    if (
        playback_started
    )
    {
        ESP_LOGI(
            TAG,
            "FINISHED"
        );


        send_music_event(
            MUSIC_EVENT_FINISHED
        );


        return PLAY_RESULT_FINISHED;
    }


    send_music_event(
        MUSIC_EVENT_ERROR
    );


    return PLAY_RESULT_ERROR;
}


/* ============================================================
 * MUSIC TASK
 * ============================================================ */

static void music_task(
    void *arg
)
{
    (void)arg;


    ESP_LOGI(
        TAG,
        "Music task started, stack free=%u",
        (unsigned)
        uxTaskGetStackHighWaterMark(
            NULL
        )
    );


    player_command_t command;


    char current_path[
        MUSIC_PATH_MAX
    ];


    char restart_path[
        MUSIC_PATH_MAX
    ];


    while (1)
    {
        /* ====================================================
         * IDLE
         *
         * START 명령 기다림
         * ==================================================== */

        if (
            xQueueReceive(
                s_command_queue,

                &command,

                portMAX_DELAY
            )
            !=
            pdTRUE
        )
        {
            continue;
        }


        if (command.type == PLAYER_CMD_STOP) {
            confirm_stopped(&command);
            continue;
        }

        if (
            command.type !=
            PLAYER_CMD_START
        )
        {
            continue;
        }


        if (
            !copy_path(
                current_path,

                sizeof(current_path),

                command.path
            )
        )
        {
            continue;
        }


        /* ====================================================
         * PLAY / RESTART LOOP
         * ==================================================== */

        while (1)
        {
            play_result_t result =
                play_mp3_file(
                    current_path,

                    restart_path,

                    sizeof(restart_path)
                );


            if (
                result ==
                PLAY_RESULT_RESTART
            )
            {
                if (
                    !copy_path(
                        current_path,

                        sizeof(current_path),

                        restart_path
                    )
                )
                {
                    break;
                }


                continue;
            }


            break;
        }
    }
}


/* ============================================================
 * COMMAND SEND
 * ============================================================ */

static bool send_command(
    player_command_type_t type,
    const char *path
)
{
    if (
        s_command_queue ==
        NULL
    )
    {
        return false;
    }


    player_command_t command;


    memset(
        &command,
        0,
        sizeof(command)
    );


    command.type =
        type;


    if (
        path !=
        NULL
    )
    {
        if (
            !copy_path(
                command.path,

                sizeof(command.path),

                path
            )
        )
        {
            return false;
        }
    }


    return
        xQueueSend(
            s_command_queue,

            &command,

            pdMS_TO_TICKS(
                100
            )
        )
        ==
        pdTRUE;
}


/* ============================================================
 * INIT
 * ============================================================ */

bool music_player_init(void)
{
    if (
        s_command_queue !=
        NULL
    )
    {
        return true;
    }


    s_command_queue =
        xQueueCreate(
            MUSIC_COMMAND_QUEUE_LENGTH,

            sizeof(player_command_t)
        );


    if (
        s_command_queue ==
        NULL
    )
    {
        return false;
    }


    /* EQ is optional: a failed worker allocation must not stop music. */
    music_eq_init();

    BaseType_t result =
        xTaskCreate(
            music_task,

            "music_player",

            MUSIC_TASK_STACK_SIZE,

            NULL,

            MUSIC_TASK_PRIORITY,

            &s_music_task
        );


    if (
        result !=
        pdPASS
    )
    {
        vQueueDelete(
            s_command_queue
        );


        s_command_queue =
            NULL;


        return false;
    }


    ESP_LOGI(
        TAG,
        "Music player ready"
    );


    return true;
}


/* ============================================================
 * START
 * ============================================================ */

bool music_player_start(
    const char *path
)
{
    if (
        path ==
        NULL
    )
    {
        return false;
    }


    ESP_LOGI(
        TAG,
        "START request: %s",
        path
    );


    return send_command(
        PLAYER_CMD_START,
        path
    );
}


/* ============================================================
 * STOP
 * ============================================================ */

bool music_player_stop_confirmed(uint8_t rail, const uint8_t request_id[4])
{
    if (s_command_queue == NULL) return false;
    player_command_t command = {.type = PLAYER_CMD_STOP, .confirm_stop = true,
                                .confirm_rail = rail};
    memcpy(command.request_id, request_id, 4);
    return xQueueSend(s_command_queue, &command, pdMS_TO_TICKS(100)) == pdTRUE;
}

bool music_player_stop(void)
{
    ESP_LOGI(
        TAG,
        "STOP request"
    );


    return send_command(
        PLAYER_CMD_STOP,
        NULL
    );
}


/* ============================================================
 * PAUSE
 * ============================================================ */

bool music_player_pause(void)
{
    ESP_LOGI(
        TAG,
        "PAUSE request"
    );


    return send_command(
        PLAYER_CMD_PAUSE,
        NULL
    );
}


/* ============================================================
 * RESUME
 * ============================================================ */

bool music_player_resume(void)
{
    ESP_LOGI(
        TAG,
        "RESUME request"
    );


    return send_command(
        PLAYER_CMD_RESUME,
        NULL
    );
}


/* ============================================================
 * STATE
 * ============================================================ */

music_player_state_t
music_player_get_state(void)
{
    return s_state;
}


bool music_player_is_playing(void)
{
    return
        s_state ==
        MUSIC_PLAYER_PLAYING
        ||
        s_state ==
        MUSIC_PLAYER_PAUSED;
}


bool music_player_is_paused(void)
{
    return
        s_state ==
        MUSIC_PLAYER_PAUSED;
}