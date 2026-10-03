#include "mp3_player_test.h"

#include <fcntl.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include <unistd.h>

#include "audio_output.h"
#include "sd_card.h"

#include "esp_attr.h"
#include "esp_log.h"

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"


/* ============================================================
 * MINIMP3
 *
 * 반드시 프로젝트 전체에서 여기 한 곳만
 * MINIMP3_IMPLEMENTATION 정의.
 * ============================================================ */

#define MINIMP3_ONLY_MP3
#define MINIMP3_NO_SIMD
#define MINIMP3_IMPLEMENTATION

#include "minimp3.h"


static const char *TAG =
    "MP3_TEST";


#define TEST_MP3_PATH \
    "/sdcard/music/20/DOHKYU~1.MP3"


#define MP3_INPUT_BUFFER_SIZE \
    (16 * 1024)


#define SD_READ_SIZE \
    512


/* ============================================================
 * STATIC BUFFER
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
 * ID3
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
        "ID3v2 skip %lu bytes",
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
 * PLAY
 * ============================================================ */

static bool play_mp3(
    const char *path
)
{
    if (
        !sd_card_is_mounted()
    )
    {
        ESP_LOGE(
            TAG,
            "SD not mounted"
        );


        return false;
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
            "open failed"
        );


        return false;
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


        return false;
    }


    mp3dec_init(
        &s_decoder
    );


    size_t buffer_len =
        0;


    bool eof =
        false;


    bool audio_started =
        false;


    uint64_t decoded_sample_frames =
        0;


    uint32_t last_second =
        UINT32_MAX;


    while (1)
    {
        /* ====================================================
         * INPUT BUFFER 채우기
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


                return false;
            }


            /*
             * 계속 SD read만 수행해서
             * idle task를 굶기지 않게 함.
             */

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
         * INPUT CONSUME
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


                return false;
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
                info.hz <= 0
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


                return false;
            }


            if (
                !audio_started
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


                    return false;
                }


                audio_started =
                    true;
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


                    return false;
                }
            }


            size_t output_samples =
                0;


            const int16_t *output =
                NULL;


            /* ================================================
             * STEREO
             * ================================================ */

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


            /* ================================================
             * MONO -> STEREO
             * ================================================ */

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


                return false;
            }


            decoded_sample_frames +=
                (uint64_t)samples;


            uint32_t sec =
                (uint32_t)(
                    decoded_sample_frames
                    /
                    (uint64_t)info.hz
                );


            if (
                sec !=
                last_second
            )
            {
                last_second =
                    sec;


                ESP_LOGI(
                    TAG,
                    "Playing: %lu sec",
                    (unsigned long)sec
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


        vTaskDelay(
            1
        );
    }


    close(
        fd
    );


    audio_output_deinit();


    ESP_LOGI(
        TAG,
        "MP3 finished"
    );


    return audio_started;
}


/* ============================================================
 * TASK
 * ============================================================ */

void mp3_player_test_task(
    void *arg
)
{
    (void)arg;


    /*
     * 다른 초기화 완료 대기
     */

    vTaskDelay(
        pdMS_TO_TICKS(
            1000
        )
    );


    ESP_LOGI(
        TAG,
        "MP3 task started, stack free=%u",
        (unsigned)
        uxTaskGetStackHighWaterMark(
            NULL
        )
    );


    bool ok =
        play_mp3(
            TEST_MP3_PATH
        );


    if (
        ok
    )
    {
        ESP_LOGI(
            TAG,
            "MP3 PLAYBACK SUCCESS"
        );
    }
    else
    {
        ESP_LOGE(
            TAG,
            "MP3 PLAYBACK FAILED"
        );
    }


    vTaskDelete(
        NULL
    );
}