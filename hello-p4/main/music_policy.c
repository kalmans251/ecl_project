#include "music_policy.h"

#include <string.h>

#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/queue.h"

#include "esp_log.h"

#include "board_config.h"
#include "protocol.h"
#include "router.h"
#include "system_state.h"


static const char *TAG =
    "MUSIC_POLICY";


static SemaphoreHandle_t
    s_mutex =
        NULL;


/*
 * 현재 음악을 막고 있는 이유.
 */
static uint32_t
    s_pause_reasons =
        MUSIC_PAUSE_REASON_NONE;


/* ============================================================
 * LOCK
 * ============================================================ */

static void lock_policy(void)
{
    xSemaphoreTake(
        s_mutex,
        portMAX_DELAY
    );
}


static void unlock_policy(void)
{
    xSemaphoreGive(
        s_mutex
    );
}


/* ============================================================
 * SEND TO WROOM
 * ============================================================ */

static bool send_music_command(
    uint8_t command
)
{
    protocol_frame_t frame;


    memset(
        &frame,
        0,
        sizeof(frame)
    );


    frame.railing_id =
        RAILING_ID;

    frame.src =
        NODE_P4;

    frame.dst =
        NODE_WROOM;

    frame.service =
        SERVICE_MUSIC;

    frame.command =
        command;

    frame.length =
        0;


    return
        xQueueSend(
            router_queue,
            &frame,
            pdMS_TO_TICKS(100)
        )
        ==
        pdTRUE;
}


/* ============================================================
 * INIT
 * ============================================================ */

void music_policy_init(void)
{
    s_mutex =
        xSemaphoreCreateMutex();


    if (
        s_mutex ==
        NULL
    )
    {
        ESP_LOGE(
            TAG,
            "Mutex create failed"
        );

        abort();
    }


    s_pause_reasons =
        MUSIC_PAUSE_REASON_NONE;


    ESP_LOGI(
        TAG,
        "Music policy initialized"
    );
}


/* ============================================================
 * ADD REASON
 * ============================================================ */

void music_policy_add_pause_reason(
    music_pause_reason_t reason
)
{
    if (
        reason ==
        MUSIC_PAUSE_REASON_NONE
    )
    {
        return;
    }


    p4_system_state_t state;


    system_state_get(
        &state
    );


    lock_policy();


    uint32_t previous =
        s_pause_reasons;


    s_pause_reasons |=
        (uint32_t)reason;


    uint32_t current =
        s_pause_reasons;


    unlock_policy();


    ESP_LOGI(
        TAG,
        "Pause reason ADD 0x%02lX -> mask=0x%02lX",
        (unsigned long)reason,
        (unsigned long)current
    );


    /*
     * 이전에는 아무 이유도 없었는데
     * 처음으로 block이 생긴 경우에만 실제 PAUSE.
     */
    if (
        previous ==
        MUSIC_PAUSE_REASON_NONE
        &&
        current !=
        MUSIC_PAUSE_REASON_NONE
        &&
        state.music_playing
    )
    {
        ESP_LOGI(
            TAG,
            "MUSIC -> PAUSE"
        );


        send_music_command(
            CMD_PAUSE
        );
    }
}


/* ============================================================
 * REMOVE REASON
 * ============================================================ */

void music_policy_remove_pause_reason(
    music_pause_reason_t reason
)
{
    if (
        reason ==
        MUSIC_PAUSE_REASON_NONE
    )
    {
        return;
    }


    lock_policy();


    uint32_t previous =
        s_pause_reasons;


    s_pause_reasons &=
        ~((uint32_t)reason);


    uint32_t current =
        s_pause_reasons;


    unlock_policy();


    ESP_LOGI(
        TAG,
        "Pause reason REMOVE 0x%02lX -> mask=0x%02lX",
        (unsigned long)reason,
        (unsigned long)current
    );


    /*
     * 다른 block 이유가 하나도 남지 않았을 때만 RESUME.
     */
    if (
        previous !=
        MUSIC_PAUSE_REASON_NONE
        &&
        current ==
        MUSIC_PAUSE_REASON_NONE
    )
    {
        p4_system_state_t state;


        system_state_get(
            &state
        );


        /*
         * 실제로 이어서 재생 가능한 상태에서만.
         */
        if (
            state.music_enabled
            &&
            !state.music_playing
            &&
            !state.sleep_active
        )
        {
            ESP_LOGI(
                TAG,
                "MUSIC -> RESUME"
            );


            send_music_command(
                CMD_RESUME
            );
        }
    }
}


/* ============================================================
 * GET
 * ============================================================ */

uint32_t music_policy_get_pause_reasons(void)
{
    uint32_t reasons;


    lock_policy();

    reasons =
        s_pause_reasons;

    unlock_policy();


    return reasons;
}


bool music_policy_is_blocked(void)
{
    return
        music_policy_get_pause_reasons()
        !=
        MUSIC_PAUSE_REASON_NONE;
}


/* ============================================================
 * PLAYER EVENTS
 * ============================================================ */

void music_policy_on_started(void)
{
    system_state_set_music_enabled(
        true
    );


    system_state_set_music_playing(
        true
    );
}


void music_policy_on_paused(void)
{
    /*
     * 곡 자체는 살아 있음.
     */
    system_state_set_music_enabled(
        true
    );


    system_state_set_music_playing(
        false
    );
}


void music_policy_on_resumed(void)
{
    system_state_set_music_enabled(
        true
    );


    system_state_set_music_playing(
        true
    );
}


void music_policy_on_finished(void)
{
    system_state_set_music_playing(
        false
    );


    /*
     * 지금 단계에서는 기존 의미 유지.
     *
     * 다음 playlist 단계에서
     * music_enabled 대신 session_active로 분리 예정.
     */
    system_state_set_music_enabled(
        false
    );
}


void music_policy_on_error(void)
{
    system_state_set_music_playing(
        false
    );


    system_state_set_music_enabled(
        false
    );
}