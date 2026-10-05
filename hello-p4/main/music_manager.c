#include "music_manager.h"

#include <string.h>

#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/queue.h"

#include "esp_log.h"

#include "board_config.h"
#include "router.h"
#include "music_policy.h"


static const char *TAG =
    "MUSIC_MANAGER";


/* ============================================================
 * STATE
 * ============================================================ */

static SemaphoreHandle_t
    s_mutex =
        NULL;


/*
 * 재생 방식.
 *
 * 기본은 순차.
 */
static music_play_mode_t
    s_mode =
        MUSIC_PLAY_MODE_SEQUENTIAL;


/*
 * 현재 AGE 그룹.
 *
 * AGE 모드가 아니어도 값 자체는 기억 가능.
 */
static music_group_t
    s_group =
        MUSIC_GROUP_DEFAULT;


/*
 * 음악 시스템 자체를 사용자가 START했는지.
 *
 * 곡 하나가 FINISHED 되어도 false가 되지 않는다.
 */
static bool
    s_session_enabled =
        false;


/*
 * SLEEP_PENDING 중 현재 곡이 끝난 경우.
 *
 * 다음 사람 감지 시 NEXT 해야 함.
 */
static bool
    s_next_on_wake =
        false;


/* ============================================================
 * LOCK
 * ============================================================ */

static void lock_manager(void)
{
    xSemaphoreTake(
        s_mutex,
        portMAX_DELAY
    );
}


static void unlock_manager(void)
{
    xSemaphoreGive(
        s_mutex
    );
}


/* ============================================================
 * SEND WROOM
 * ============================================================ */

static bool send_music_command(
    uint8_t command,
    const uint8_t *payload,
    uint8_t length
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
        length;


    if (
        payload != NULL &&
        length > 0
    )
    {
        memcpy(
            frame.payload,
            payload,
            length
        );
    }


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
 * SET WROOM MODE
 * ============================================================ */

static bool send_play_mode(
    music_play_mode_t mode
)
{
    uint8_t payload[2];


    payload[0] =
        MUSIC_SET_PLAY_MODE;

    payload[1] =
        (uint8_t)mode;


    return
        send_music_command(
            CMD_SET,
            payload,
            sizeof(payload)
        );
}


/* ============================================================
 * SET WROOM GROUP
 * ============================================================ */

static bool send_group(
    music_group_t group
)
{
    uint8_t payload[2];


    payload[0] =
        MUSIC_SET_GROUP;

    payload[1] =
        (uint8_t)group;


    return
        send_music_command(
            CMD_SET,
            payload,
            sizeof(payload)
        );
}


/* ============================================================
 * AGE -> GROUP
 * ============================================================ */

static music_group_t age_to_group(
    age_group_t age
)
{
    switch (
        age
    )
    {
        case AGE_GROUP_10S:
            return MUSIC_GROUP_10S;

        case AGE_GROUP_20S:
            return MUSIC_GROUP_20S;

        case AGE_GROUP_30S:
            return MUSIC_GROUP_30S;

        case AGE_GROUP_40S:
            return MUSIC_GROUP_40S;

        default:
            return MUSIC_GROUP_DEFAULT;
    }
}


/* ============================================================
 * INIT
 * ============================================================ */

void music_manager_init(void)
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


    s_mode =
        MUSIC_PLAY_MODE_SEQUENTIAL;

    s_group =
        MUSIC_GROUP_DEFAULT;

    s_session_enabled =
        false;

    s_next_on_wake =
        false;


    ESP_LOGI(
        TAG,
        "Music manager initialized / SEQUENTIAL"
    );
}


/* ============================================================
 * SET MODE
 * ============================================================ */

bool music_manager_set_mode(
    music_play_mode_t mode
)
{
    if (
        mode !=
            MUSIC_PLAY_MODE_SEQUENTIAL
        &&
        mode !=
            MUSIC_PLAY_MODE_SHUFFLE
        &&
        mode !=
            MUSIC_PLAY_MODE_AGE
    )
    {
        return false;
    }


    detection_source_t source =
        detection_manager_get_source();


    /*
     * RADAR에는 AGE 정보가 없으므로
     * AGE 재생 자체를 허용하지 않는다.
     */
    if (
        mode ==
            MUSIC_PLAY_MODE_AGE
        &&
        source !=
            DETECTION_SOURCE_CCTV
    )
    {
        ESP_LOGW(
            TAG,
            "AGE mode rejected: detection source is RADAR"
        );


        return false;
    }


    music_group_t group =
        MUSIC_GROUP_DEFAULT;


    /*
     * AGE 모드를 처음 켤 때
     * 현재까지 가장 최근에 정상 판별된 연령대를 사용.
     *
     * 아직 연령대가 없다면 DEFAULT.
     */
    if (
        mode ==
        MUSIC_PLAY_MODE_AGE
    )
    {
        detection_summary_t detection;


        detection_manager_get_summary(
            &detection
        );


        group =
            age_to_group(
                detection.latest_age_group
            );


        /*
         * WROOM에 group을 먼저 알려준 뒤
         * AGE mode를 켠다.
         */
        send_group(
            group
        );
    }


    if (
        !send_play_mode(
            mode
        )
    )
    {
        ESP_LOGW(
            TAG,
            "Failed to send play mode"
        );


        return false;
    }


    lock_manager();


    s_mode =
        mode;


    if (
        mode ==
        MUSIC_PLAY_MODE_AGE
    )
    {
        s_group =
            group;
    }
    else
    {
        s_group =
            MUSIC_GROUP_DEFAULT;
    }


    unlock_manager();


    ESP_LOGI(
        TAG,
        "MODE -> %d / GROUP=%d",
        mode,
        group
    );


    return true;
}


/* ============================================================
 * GET MODE
 * ============================================================ */

music_play_mode_t
music_manager_get_mode(void)
{
    music_play_mode_t mode;


    lock_manager();

    mode =
        s_mode;

    unlock_manager();


    return mode;
}


/* ============================================================
 * START SESSION
 * ============================================================ */

bool music_manager_start(void)
{
    bool already_enabled;


    lock_manager();

    already_enabled =
        s_session_enabled;


    /*
     * 이미 음악 세션이 켜져 있으면
     * START를 다시 WROOM으로 보내지 않는다.
     *
     * 따라서 START 버튼을 여러 번 눌러도
     * 현재 곡이 바뀌거나 재시작되지 않는다.
     */
    if (
        already_enabled
    )
    {
        unlock_manager();


        ESP_LOGI(
            TAG,
            "START ignored: session already enabled"
        );


        return true;
    }


    s_session_enabled =
        true;

    s_next_on_wake =
        false;


    unlock_manager();


    p4_system_state_t state;


    system_state_get(
        &state
    );


    /*
     * Sleep 중에는 세션만 활성화.
     * 실제 재생은 Wake 시 시작.
     */
    if (
        state.sleep_active
    )
    {
        ESP_LOGI(
            TAG,
            "START armed while sleeping"
        );


        return true;
    }


    /*
     * BASIC / WEATHER 상태에서도
     * 세션만 활성화.
     */
    if (
        state.led_mode !=
            LED_MODE_MUSIC
    )
    {
        ESP_LOGI(
            TAG,
            "START armed while LED mode is not MUSIC"
        );


        return true;
    }


    bool sent =
        send_music_command(
            CMD_START,
            NULL,
            0
        );


    /*
     * 실제 START 명령 자체를 전달하지 못했다면
     * 세션 활성화도 취소.
     */
    if (
        !sent
    )
    {
        lock_manager();

        s_session_enabled =
            false;

        unlock_manager();


        ESP_LOGW(
            TAG,
            "START send failed"
        );
    }


    return sent;
}


/* ============================================================
 * STOP SESSION
 * ============================================================ */

bool music_manager_stop(void)
{
    lock_manager();


    s_session_enabled =
        false;

    s_next_on_wake =
        false;


    unlock_manager();


    ESP_LOGI(
        TAG,
        "SESSION STOP"
    );


    return
        send_music_command(
            CMD_STOP,
            NULL,
            0
        );
}


/* ============================================================
 * NEXT
 * ============================================================ */

bool music_manager_next(void)
{
    bool enabled;


    lock_manager();

    enabled =
        s_session_enabled;

    unlock_manager();


    if (
        !enabled
    )
    {
        ESP_LOGW(
            TAG,
            "NEXT ignored: session disabled"
        );


        return false;
    }


    p4_system_state_t state;


    system_state_get(
        &state
    );


    if (
        state.sleep_active
    )
    {
        lock_manager();

        s_next_on_wake =
            true;

        unlock_manager();


        ESP_LOGI(
            TAG,
            "NEXT reserved for wake"
        );


        return true;
    }


    if (
        state.led_mode !=
            LED_MODE_MUSIC
    )
    {
        return false;
    }


    return
        send_music_command(
            CMD_NEXT,
            NULL,
            0
        );
}


/* ============================================================
 * SESSION STATE
 * ============================================================ */

bool music_manager_is_session_enabled(void)
{
    bool enabled;


    lock_manager();

    enabled =
        s_session_enabled;

    unlock_manager();


    return enabled;
}


/* ============================================================
 * USER PAUSE
 * ============================================================ */

void music_manager_user_pause(void)
{
    music_policy_add_pause_reason(
        MUSIC_PAUSE_REASON_USER
    );
}


void music_manager_user_resume(void)
{
    music_policy_remove_pause_reason(
        MUSIC_PAUSE_REASON_USER
    );
}


/* ============================================================
 * SOURCE CHANGED
 * ============================================================ */

void music_manager_on_detection_source_changed(
    detection_source_t source
)
{
    music_play_mode_t mode;


    lock_manager();

    mode =
        s_mode;

    unlock_manager();


    /*
     * CCTV AGE 모드에서 RADAR로 변경되면
     * AGE 모드를 사용할 수 없으므로
     * SEQUENTIAL로 자동 fallback.
     */
    if (
        source ==
            DETECTION_SOURCE_RADAR
        &&
        mode ==
            MUSIC_PLAY_MODE_AGE
    )
    {
        ESP_LOGI(
            TAG,
            "CCTV AGE -> RADAR : fallback SEQUENTIAL"
        );


        send_play_mode(
            MUSIC_PLAY_MODE_SEQUENTIAL
        );


        lock_manager();

        s_mode =
            MUSIC_PLAY_MODE_SEQUENTIAL;

        s_group =
            MUSIC_GROUP_DEFAULT;

        unlock_manager();
    }
}


/* ============================================================
 * AGE RESULT
 * ============================================================ */

void music_manager_on_age_result(
    age_group_t age
)
{
    music_play_mode_t mode;


    lock_manager();

    mode =
        s_mode;

    unlock_manager();


    if (
        mode !=
        MUSIC_PLAY_MODE_AGE
    )
    {
        return;
    }


    if (
        detection_manager_get_source()
        !=
        DETECTION_SOURCE_CCTV
    )
    {
        return;
    }


    /*
     * 판별 실패:
     * 현재 연령대 그룹 유지.
     */
    if (
        age ==
        AGE_GROUP_KEEP_CURRENT
    )
    {
        ESP_LOGI(
            TAG,
            "AGE KEEP_CURRENT"
        );


        return;
    }


    music_group_t group =
        age_to_group(
            age
        );


    /*
     * 정상 AGE가 아닌 경우 DEFAULT.
     */
    if (
        group ==
            MUSIC_GROUP_DEFAULT
    )
    {
        return;
    }


    lock_manager();

    s_group =
        group;

    unlock_manager();


    send_group(
        group
    );


    ESP_LOGI(
        TAG,
        "AGE -> GROUP %d",
        group
    );
}


/* ============================================================
 * TRACK FINISHED
 * ============================================================ */

void music_manager_on_track_finished(
    bool entered_sleep
)
{
    bool enabled;


    lock_manager();

    enabled =
        s_session_enabled;


    if (
        entered_sleep &&
        enabled
    )
    {
        s_next_on_wake =
            true;
    }


    unlock_manager();


    if (
        !enabled
    )
    {
        return;
    }


    /*
     * Sleep Pending으로 인해 잠든 경우:
     *
     * 다음 곡을 지금 시작하지 않는다.
     */
    if (
        entered_sleep
    )
    {
        ESP_LOGI(
            TAG,
            "FINISHED -> NEXT reserved for wake"
        );


        return;
    }


    p4_system_state_t state;


    system_state_get(
        &state
    );


    /*
     * 아직 Active이며 MUSIC LED 모드라면
     * 다음 곡 자동 재생.
     */
    if (
        !state.sleep_active
        &&
        state.led_mode ==
            LED_MODE_MUSIC
    )
    {
        ESP_LOGI(
            TAG,
            "FINISHED -> NEXT"
        );


        send_music_command(
            CMD_NEXT,
            NULL,
            0
        );
    }
}


/* ============================================================
 * WAKE
 * ============================================================ */

void music_manager_on_wake(void)
{
    bool enabled;

    bool next_on_wake;


    lock_manager();


    enabled =
        s_session_enabled;

    next_on_wake =
        s_next_on_wake;


    unlock_manager();


    if (
        !enabled
    )
    {
        return;
    }


    p4_system_state_t state;


    system_state_get(
        &state
    );


    /*
     * BASIC / WEATHER에서는
     * 음악을 재생하지 않는다.
     */
    if (
        state.led_mode !=
            LED_MODE_MUSIC
    )
    {
        return;
    }


    /*
     * Sleep 전에 현재 곡이 끝났다면
     * 다음 곡부터 시작.
     */
    if (
        next_on_wake
    )
    {
        ESP_LOGI(
            TAG,
            "WAKE -> NEXT"
        );


        if (
            send_music_command(
                CMD_NEXT,
                NULL,
                0
            )
        )
        {
            lock_manager();

            s_next_on_wake =
                false;

            unlock_manager();
        }


        return;
    }


    /*
     * Sleep 전에 실제 곡 자체가 없었다면 START.
     */
    system_state_get(
        &state
    );


    if (
        !state.music_enabled
    )
    {
        ESP_LOGI(
            TAG,
            "WAKE -> START"
        );


        send_music_command(
            CMD_START,
            NULL,
            0
        );
    }
    else if (!state.sleep_active && !state.call_active && !music_policy_is_blocked())
    {
        /* LED mode may have removed its pause reason while still sleeping.
         * No reason transition occurs at wake, so explicitly resume that track.
         * Do not rely on music_playing: WROOM's PAUSED event may still be in
         * transit. RESUME is idempotent and follows PAUSE on the same UART.
         */
        ESP_LOGI(TAG, "WAKE -> RESUME existing track");
        send_music_command(CMD_RESUME, NULL, 0);
    }
}


/* ============================================================
 * LED MODE
 * ============================================================ */

void music_manager_on_led_mode_changed(
    led_mode_t mode
)
{
    if (
        mode !=
        LED_MODE_MUSIC
    )
    {
        return;
    }


    bool enabled;


    lock_manager();

    enabled =
        s_session_enabled;

    unlock_manager();


    if (
        !enabled
    )
    {
        return;
    }


    p4_system_state_t state;


    system_state_get(
        &state
    );


    if (
        state.sleep_active
    )
    {
        return;
    }


    /*
     * 기존 곡이 PAUSE 상태라면
     * music_policy가 RESUME해준다.
     *
     * 곡 자체가 없다면 START.
     */
    if (
        !state.music_enabled
    )
    {
        send_music_command(
            CMD_START,
            NULL,
            0
        );
    }
}


/* ============================================================
 * AGE WAIT REQUIRED
 * ============================================================ */

bool music_manager_requires_age_for_wake(void)
{
    music_play_mode_t mode;


    lock_manager();

    mode =
        s_mode;

    unlock_manager();


    return
        detection_manager_get_source()
            ==
            DETECTION_SOURCE_CCTV
        &&
        mode ==
            MUSIC_PLAY_MODE_AGE;
}