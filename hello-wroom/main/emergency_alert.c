#include "emergency_alert.h"

#include <stdint.h>

#include "audio_output.h"
#include "music_player.h"

#include "esp_log.h"

#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"


static const char *TAG =
    "EMERGENCY_ALERT";


#define ALERT_SAMPLE_RATE             16000U
#define ALERT_FRAME_SAMPLES           160U
#define ALERT_PCM_SAMPLES             (ALERT_FRAME_SAMPLES * 2U)

#define ALERT_FREQ_HIGH               880U
#define ALERT_FREQ_LOW                660U

#define ALERT_SWITCH_INTERVAL_MS      350U
#define ALERT_VOLUME_PERCENT          70U

#define ALERT_TASK_STACK_SIZE         4096
#define ALERT_TASK_PRIORITY           9
#define ALERT_COMMAND_QUEUE_LENGTH    4


typedef enum
{
    ALERT_COMMAND_START =
        1,

    ALERT_COMMAND_STOP =
        2

} alert_command_t;


static QueueHandle_t
    s_command_queue =
        NULL;


static volatile bool
    s_requested_active =
        false;


static volatile bool
    s_active =
        false;


static int16_t
    s_pcm[
        ALERT_PCM_SAMPLES
    ];


static void generate_square_tone(
    uint32_t frequency,
    uint32_t *phase
)
{
    if (
        phase ==
        NULL
    )
    {
        return;
    }


    for (
        uint32_t i = 0;
        i < ALERT_FRAME_SAMPLES;
        i++
    )
    {
        int16_t sample =
            (
                *phase <
                (
                    ALERT_SAMPLE_RATE /
                    2U
                )
            )
            ?
            24000
            :
            -24000;


        s_pcm[
            i * 2U
        ] =
            sample;

        s_pcm[
            i * 2U + 1U
        ] =
            sample;


        *phase +=
            frequency;


        if (
            *phase >=
            ALERT_SAMPLE_RATE
        )
        {
            *phase -=
                ALERT_SAMPLE_RATE;
        }
    }
}


static void consume_pending_commands(void)
{
    alert_command_t command;


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
        if (
            command ==
            ALERT_COMMAND_STOP
        )
        {
            s_requested_active =
                false;
        }
        else if (
            command ==
            ALERT_COMMAND_START
        )
        {
            s_requested_active =
                true;
        }
    }
}


static bool wait_for_music_pause(void)
{
    music_player_pause();


    while (
        s_requested_active
    )
    {
        consume_pending_commands();


        music_player_state_t state =
            music_player_get_state();


        if (
            state ==
                MUSIC_PLAYER_IDLE
            ||
            state ==
                MUSIC_PLAYER_PAUSED
        )
        {
            return true;
        }


        vTaskDelay(
            pdMS_TO_TICKS(
                10
            )
        );
    }


    return false;
}


static void play_alert(void)
{
    if (
        !wait_for_music_pause()
    )
    {
        return;
    }


    bool audio_was_initialized =
        audio_output_is_initialized();


    uint32_t previous_sample_rate =
        audio_output_get_sample_rate();


    uint8_t previous_volume =
        audio_output_get_volume();


    if (
        !audio_output_init(
            ALERT_SAMPLE_RATE
        )
    )
    {
        ESP_LOGE(
            TAG,
            "I2S init failed"
        );


        return;
    }


    audio_output_set_volume(
        ALERT_VOLUME_PERCENT
    );


    uint32_t phase =
        0;


    TickType_t tone_started =
        xTaskGetTickCount();


    bool high_tone =
        true;


    s_active =
        true;


    ESP_LOGW(
        TAG,
        "ALERT START"
    );


    while (
        s_requested_active
    )
    {
        consume_pending_commands();


        if (
            !s_requested_active
        )
        {
            break;
        }


        TickType_t now =
            xTaskGetTickCount();


        if (
            (
                now -
                tone_started
            )
            >=
            pdMS_TO_TICKS(
                ALERT_SWITCH_INTERVAL_MS
            )
        )
        {
            high_tone =
                !high_tone;


            tone_started =
                now;
        }


        generate_square_tone(
            high_tone
                ?
                ALERT_FREQ_HIGH
                :
                ALERT_FREQ_LOW,
            &phase
        );


        if (
            !audio_output_write(
                s_pcm,
                ALERT_PCM_SAMPLES
            )
        )
        {
            ESP_LOGE(
                TAG,
                "Audio write failed"
            );


            break;
        }
    }


    audio_output_set_volume(
        previous_volume
    );


    if (
        audio_was_initialized
        &&
        previous_sample_rate >
            0
    )
    {
        if (
            !audio_output_set_sample_rate(
                previous_sample_rate
            )
        )
        {
            ESP_LOGE(
                TAG,
                "Failed to restore sample rate=%lu",
                (unsigned long)
                    previous_sample_rate
            );
        }
    }
    else
    {
        audio_output_deinit();
    }


    s_active =
        false;


    ESP_LOGI(
        TAG,
        "ALERT STOP"
    );
}


static void emergency_alert_task(
    void *arg
)
{
    (void)arg;


    alert_command_t command;


    while (1)
    {
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


        if (
            command ==
            ALERT_COMMAND_STOP
        )
        {
            s_requested_active =
                false;


            continue;
        }


        if (
            command !=
            ALERT_COMMAND_START
        )
        {
            continue;
        }


        /*
         * START가 처리되기 전에 STOP이 들어온 경우
         * stale START를 다시 활성화하지 않는다.
         */
        if (
            !s_requested_active
        )
        {
            continue;
        }


        play_alert();


        s_active =
            false;

        s_requested_active =
            false;
    }
}


bool emergency_alert_init(void)
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
            ALERT_COMMAND_QUEUE_LENGTH,
            sizeof(alert_command_t)
        );


    if (
        s_command_queue ==
        NULL
    )
    {
        return false;
    }


    if (
        xTaskCreate(
            emergency_alert_task,
            "emergency_alert",
            ALERT_TASK_STACK_SIZE,
            NULL,
            ALERT_TASK_PRIORITY,
            NULL
        )
        !=
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
        "Emergency alert ready"
    );


    return true;
}


bool emergency_alert_start(void)
{
    if (
        s_command_queue ==
        NULL
    )
    {
        return false;
    }


    if (
        s_requested_active
    )
    {
        return true;
    }


    s_requested_active =
        true;


    alert_command_t command =
        ALERT_COMMAND_START;


    if (
        xQueueSend(
            s_command_queue,
            &command,
            pdMS_TO_TICKS(
                100
            )
        )
        !=
        pdTRUE
    )
    {
        s_requested_active =
            false;


        return false;
    }


    return true;
}


bool emergency_alert_stop(void)
{
    if (
        s_command_queue ==
        NULL
    )
    {
        return false;
    }


    s_requested_active =
        false;


    alert_command_t command =
        ALERT_COMMAND_STOP;


    (void)
    xQueueSend(
        s_command_queue,
        &command,
        0
    );


    /*
     * P4는 이 함수가 돌아온 직후 일반 음악 RESUME을
     * 보낼 수 있다. alert가 I2S sample-rate/volume을
     * 복구할 때까지 잠깐 기다려 두 출력이 겹치지 않게 한다.
     */
    for (
        int i = 0;
        i < 50;
        i++
    )
    {
        if (
            !s_active
        )
        {
            return true;
        }


        vTaskDelay(
            pdMS_TO_TICKS(
                10
            )
        );
    }


    ESP_LOGW(
        TAG,
        "Alert stop timeout"
    );


    return
        !s_active;
}


bool emergency_alert_is_active(void)
{
    return
        s_active
        ||
        s_requested_active;
}
