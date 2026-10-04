#include <string.h>

#include "call_manager.h"

#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"

#include "esp_log.h"

#include "board_config.h"
#include "protocol.h"
#include "router.h"

#include "system_state.h"
#include "projector_control.h"
#include "music_policy.h"

static const char *TAG =
    "CALL";


/* ============================================================
 * RESTORE SNAPSHOT
 * ============================================================ */

typedef struct
{
    bool valid;


    /* --------------------------------------------------------
     * MUSIC
     * -------------------------------------------------------- */

    bool music_enabled;

    bool music_was_playing;


    /* --------------------------------------------------------
     * PROJECTOR
     * -------------------------------------------------------- */

    bool projector_enabled;


    /* --------------------------------------------------------
     * SLEEP
     * -------------------------------------------------------- */

    bool sleep_mode_enabled;

    bool sleep_active;


    /*
     * LED의 enabled/mode 자체는 Call Manager가
     * 변경하지 않으므로 별도 저장하지 않아도 됨.
     *
     * sleep_active를 잠시 false로 만들었다가
     * 복원하면 led_task가 자동으로 따라감.
     */

} call_restore_state_t;


/* ============================================================
 * INTERNAL
 * ============================================================ */

static SemaphoreHandle_t
    s_mutex =
        NULL;


static call_state_t
    s_call_state =
        CALL_STATE_IDLE;


static call_origin_t
    s_call_origin =
        CALL_ORIGIN_NORMAL;


static call_restore_state_t
    s_restore;


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
 * SEND FRAME
 *
 * P4 내부에서 생성한 명령을 Router로 보냄.
 * ============================================================ */

static bool send_frame_to_node(
    uint8_t dst,
    uint8_t service,
    uint8_t command,
    const uint8_t *payload,
    uint8_t length
)
{
    if (
        length >
        PROTOCOL_MAX_PAYLOAD
    )
    {
        return false;
    }


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
        dst;

    frame.service =
        service;

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


    if (
        xQueueSend(
            router_queue,
            &frame,
            pdMS_TO_TICKS(100)
        )
        !=
        pdTRUE
    )
    {
        ESP_LOGW(
            TAG,
            "Router queue full"
        );

        return false;
    }


    return true;
}






/* ============================================================
 * AUDIO START
 *
 * WROOM:
 * 통화모드 준비
 *
 * S3:
 * 마이크/Codec2 통화모드 준비
 * ============================================================ */

static void request_audio_start(void)
{
    send_frame_to_node(
        NODE_WROOM,
        SERVICE_AUDIO,
        CMD_START,
        NULL,
        0
    );


    send_frame_to_node(
        NODE_S3,
        SERVICE_AUDIO,
        CMD_START,
        NULL,
        0
    );
}


/* ============================================================
 * AUDIO STOP
 * ============================================================ */

static void request_audio_stop(void)
{
    send_frame_to_node(
        NODE_S3,
        SERVICE_AUDIO,
        CMD_STOP,
        NULL,
        0
    );


    send_frame_to_node(
        NODE_WROOM,
        SERVICE_AUDIO,
        CMD_STOP,
        NULL,
        0
    );
}


/* ============================================================
 * AUDIO DIRECTION
 *
 * WROOM과 S3 둘 다 방향 상태를 알아야 함.
 * ============================================================ */

static void request_audio_direction(
    audio_direction_t direction
)
{
    uint8_t payload[1];


    payload[0] =
        (uint8_t)
        direction;


    send_frame_to_node(
        NODE_WROOM,
        SERVICE_AUDIO,
        CMD_SET,
        payload,
        sizeof(payload)
    );


    send_frame_to_node(
        NODE_S3,
        SERVICE_AUDIO,
        CMD_SET,
        payload,
        sizeof(payload)
    );
}


/* ============================================================
 * PI CALL STATE EVENT
 *
 * SERVICE_AUDIO + CMD_DATA
 *
 * payload[0] = AUDIO_DATA_EVENT
 * payload[1] = audio_event_t
 * payload[2] = call_origin_t
 * payload[3] = direction
 * ============================================================ */

static void notify_pi_call_event(
    audio_event_t event,
    call_origin_t origin,
    uint8_t direction
)
{
    uint8_t payload[4];


    payload[0] =
        AUDIO_DATA_EVENT;


    payload[1] =
        (uint8_t)event;


    payload[2] =
        (uint8_t)origin;


    payload[3] =
        direction;


    if (
        !send_frame_to_node(
            NODE_PI,
            SERVICE_AUDIO,
            CMD_DATA,
            payload,
            sizeof(payload)
        )
    )
    {
        ESP_LOGW(
            TAG,
            "Failed to send PI call event=%u",
            (unsigned)event
        );
    }
}


/* ============================================================
 * SAVE RESTORE STATE
 * ============================================================ */

static void save_restore_state(void)
{
    p4_system_state_t state;


    system_state_get(
        &state
    );


    memset(
        &s_restore,
        0,
        sizeof(s_restore)
    );


    s_restore.valid =
        true;


    s_restore.music_enabled =
        state.music_enabled;


    s_restore.music_was_playing =
        state.music_playing;


    s_restore.projector_enabled =
        state.projector_enabled;


    s_restore.sleep_mode_enabled =
        state.sleep_mode_enabled;


    s_restore.sleep_active =
        state.sleep_active;


    ESP_LOGI(
        TAG,
        "State snapshot saved"
    );
}


/* ============================================================
 * INIT
 * ============================================================ */

void call_manager_init(void)
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


    memset(
        &s_restore,
        0,
        sizeof(s_restore)
    );


    s_call_state =
        CALL_STATE_IDLE;


    s_call_origin =
        CALL_ORIGIN_NORMAL;


    ESP_LOGI(
        TAG,
        "Call manager initialized"
    );
}


/* ============================================================
 * START CALL
 * ============================================================ */

bool call_manager_start(
    call_origin_t origin
)
{
    lock_manager();


    if (
        s_call_state !=
        CALL_STATE_IDLE
    )
    {
        unlock_manager();


        ESP_LOGW(
            TAG,
            "Call already active"
        );


        return false;
    }


    /*
     * 일반 통화에서는 현재 시스템 상태를 저장.
     *
     * Emergency Manager가 생기면
     * 비상 발생 직전 snapshot은 Emergency Manager가
     * 별도로 관리하게 됨.
     */

    save_restore_state();


    s_call_origin =
        origin;


    /*
     * 통화 연결 직후 기본 방향:
     *
     * 현장 -> 관제
     */
    s_call_state =
        CALL_STATE_FIELD_TX;


    unlock_manager();


    /* ========================================================
     * 시스템에 통화 중임을 알림.
     *
     * Sleep Manager는 이 값을 보고 상태전이를 정지.
     * ======================================================== */

    system_state_set_call_active(
        true
    );


    /* ========================================================
     * 통화 중에는 물리적으로 Wake.
     *
     * sleep 설정 자체는 유지.
     * ======================================================== */

    system_state_set_sleep_active(
        false
    );


    /*
     * 원래 projector 기능이 ON이었다면
     * 통화 중에도 복구.
     */

    p4_system_state_t state;


    system_state_get(
        &state
    );


    if (
        state.projector_enabled
    )
    {
        projector_control_set(
            true
        );
    }


    /* ========================================================
     * 기존 음악이 실제 재생 중이라면 PAUSE.
     *
     * STOP이 아니라 PAUSE인 이유:
     * 통화 종료 후 이어서 재생하기 위해서.
     * ======================================================== */

    /*
    * 통화 중에는 음악이 존재하는지와 관계없이
    * MUSIC 재생 자체를 block한다.
    *
    * 통화 도중 새로운 MUSIC START가 들어와도
    * music_policy_on_started()가 즉시 PAUSE시킨다.
    */
    music_policy_add_pause_reason(
        MUSIC_PAUSE_REASON_CALL
    );


    /* ========================================================
     * WROOM / S3 통화모드 시작
     * ======================================================== */

    request_audio_start();


    /*
     * 기본 FIELD_TX
     */
    request_audio_direction(
        AUDIO_DIRECTION_FIELD_TX
    );


    notify_pi_call_event(
        AUDIO_EVENT_CALL_STARTED,
        origin,
        AUDIO_DIRECTION_FIELD_TX
    );


    ESP_LOGI(
        TAG,
        "CALL START origin=%d -> FIELD_TX",
        origin
    );


    return true;
}


/* ============================================================
 * SET DIRECTION
 * ============================================================ */

bool call_manager_set_direction(
    audio_direction_t direction
)
{
    if (
        direction !=
        AUDIO_DIRECTION_FIELD_TX
        &&
        direction !=
        AUDIO_DIRECTION_CONTROL_TX
    )
    {
        return false;
    }


    lock_manager();


    if (
        s_call_state ==
        CALL_STATE_IDLE
    )
    {
        unlock_manager();


        ESP_LOGW(
            TAG,
            "Direction ignored: no active call"
        );


        return false;
    }


    if (
        direction ==
        AUDIO_DIRECTION_FIELD_TX
    )
    {
        s_call_state =
            CALL_STATE_FIELD_TX;
    }
    else
    {
        s_call_state =
            CALL_STATE_CONTROL_TX;
    }


    unlock_manager();


    request_audio_direction(
        direction
    );


    call_origin_t origin =
        call_manager_get_origin();


    notify_pi_call_event(
        AUDIO_EVENT_DIRECTION_CHANGED,
        origin,
        (uint8_t)direction
    );


    if (
        direction ==
        AUDIO_DIRECTION_FIELD_TX
    )
    {
        ESP_LOGI(
            TAG,
            "CALL -> FIELD_TX"
        );
    }
    else
    {
        ESP_LOGI(
            TAG,
            "CALL -> CONTROL_TX"
        );
    }


    return true;
}


/* ============================================================
 * END CALL
 * ============================================================ */

bool call_manager_end(void)
{
    lock_manager();


    if (
        s_call_state ==
        CALL_STATE_IDLE
    )
    {
        unlock_manager();


        ESP_LOGW(
            TAG,
            "CALL END ignored: already idle"
        );


        return false;
    }


    /*
     * 복원에 필요한 Snapshot을 로컬로 복사.
     */
    call_restore_state_t restore =
        s_restore;


    call_origin_t origin =
        s_call_origin;


    unlock_manager();


    /* ========================================================
     * 음성 경로 먼저 종료.
     * ======================================================== */

    request_audio_stop();


    /* ========================================================
     * Sleep 상태 복원
     * ======================================================== */

    if (
        restore.valid
    )
    {
        system_state_set_sleep_active(
            restore.sleep_active
        );


        /*
         * Projector 실제 출력 복원.
         */

        if (
            restore.projector_enabled &&
            !restore.sleep_active
        )
        {
            projector_control_set(
                true
            );
        }
        else
        {
            projector_control_set(
                false
            );
        }


        /*
        * 통화가 끝났으므로 CALL block은 반드시 제거.
        *
        * LED / USER / EMERGENCY 등의 다른 reason이 남아 있으면
        * music_policy가 RESUME하지 않는다.
        */
        music_policy_remove_pause_reason(
            MUSIC_PAUSE_REASON_CALL
        );
    }


    /*
     * 복원이 끝난 뒤에 Call Active를 해제.
     *
     * 그래야 복원 중 Sleep Manager가 끼어들지 않음.
     */
    system_state_set_call_active(
        false
    );


    lock_manager();


    s_call_state =
        CALL_STATE_IDLE;


    s_call_origin =
        CALL_ORIGIN_NORMAL;


    memset(
        &s_restore,
        0,
        sizeof(s_restore)
    );


    unlock_manager();


    notify_pi_call_event(
        AUDIO_EVENT_CALL_ENDED,
        origin,
        0
    );


    ESP_LOGI(
        TAG,
        "CALL END origin=%d -> IDLE",
        origin
    );


    return true;
}


/* ============================================================
 * GET
 * ============================================================ */

bool call_manager_is_active(void)
{
    bool active;


    lock_manager();

    active =
        (
            s_call_state !=
            CALL_STATE_IDLE
        );

    unlock_manager();


    return active;
}


call_state_t call_manager_get_state(void)
{
    call_state_t state;


    lock_manager();

    state =
        s_call_state;

    unlock_manager();


    return state;
}


call_origin_t call_manager_get_origin(void)
{
    call_origin_t origin;


    lock_manager();

    origin =
        s_call_origin;

    unlock_manager();


    return origin;
}