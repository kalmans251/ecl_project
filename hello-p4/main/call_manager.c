#include <string.h>

#include "call_manager.h"

#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"

#include "esp_log.h"
#include "esp_timer.h"

#include "board_config.h"
#include "protocol.h"
#include "router.h"
#include "event_outbox.h"

#include "system_state.h"
#include "projector_control.h"
#include "music_policy.h"

#define CALL_LEASE_US (10LL * 1000 * 1000)
static int64_t s_call_lease_until_us;

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


/* Preserve origin for idempotent STOP replies. */
static uint32_t s_session, s_ptt_request;
static bool s_session_ended;
static void put_session(uint8_t *p, uint32_t id) {
    p[0]=id>>24; p[1]=id>>16; p[2]=id>>8; p[3]=id;
}
static call_origin_t s_last_end_origin = CALL_ORIGIN_NORMAL;

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
    uint8_t session[4]; put_session(session, s_session);
    send_frame_to_node(
        NODE_WROOM,
        SERVICE_AUDIO,
        CMD_START,
        session,
        sizeof(session)
    );


    send_frame_to_node(
        NODE_S3,
        SERVICE_AUDIO,
        CMD_START,
        session,
        sizeof(session)
    );
}


/* ============================================================
 * AUDIO STOP
 * ============================================================ */

static void request_audio_stop(void)
{
    uint8_t session[4]; put_session(session, s_session);
    send_frame_to_node(
        NODE_S3,
        SERVICE_AUDIO,
        CMD_STOP,
        session,
        sizeof(session)
    );


    send_frame_to_node(
        NODE_WROOM,
        SERVICE_AUDIO,
        CMD_STOP,
        session,
        sizeof(session)
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
    uint8_t payload[9];
    put_session(payload+1, s_session);
    put_session(payload+5, s_ptt_request);


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
    uint8_t payload[12];
    put_session(payload+4, s_session);
    put_session(payload+8, s_ptt_request);


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
            event == AUDIO_EVENT_DIRECTION_CHANGED ? 12 : 8
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
    s_call_lease_until_us = esp_timer_get_time() + CALL_LEASE_US;
    s_last_end_origin = CALL_ORIGIN_NORMAL;
    s_session = 0;
    s_ptt_request = 0;
    s_session_ended = false;


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


    event_outbox_clear_call_end();
    s_call_origin =
        origin;
    s_call_lease_until_us = esp_timer_get_time() + CALL_LEASE_US;


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

static void notify_call_end(call_origin_t origin, bool polled_only) {
    protocol_frame_t frame={.railing_id=RAILING_ID,.src=NODE_P4,.dst=NODE_PI,
        .service=SERVICE_AUDIO,.command=CMD_DATA,.length=8,
        .payload={AUDIO_DATA_EVENT,AUDIO_EVENT_CALL_ENDED,(uint8_t)origin,0}};
    put_session(frame.payload+4, s_session);
    s_session_ended = true;
    event_outbox_store_call_end(&frame);
    if(!polled_only)notify_pi_call_event(AUDIO_EVENT_CALL_ENDED,origin,0);
}

static bool end_call(bool polled_only)
{
    lock_manager();


    if (
        s_call_state ==
        CALL_STATE_IDLE
    )
    {
        call_origin_t origin = s_last_end_origin;
        unlock_manager();
        /* Idempotent STOP: the first END event may have been lost. */
        notify_call_end(origin, polled_only);

        ESP_LOGW(
            TAG,
            "CALL already idle -> resend END confirmation"
        );


        return true;
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


    s_last_end_origin = origin;

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


    notify_call_end(origin, polled_only);


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

bool call_manager_end(void) { return end_call(false); }

/* Retained for source compatibility; an idle node no longer grants the bus. */
bool call_manager_end_recovery_active(void) { return false; }

void call_manager_keepalive(void)
{
    lock_manager();
    if (s_call_state != CALL_STATE_IDLE && esp_timer_get_time() < s_call_lease_until_us)
        s_call_lease_until_us = esp_timer_get_time() + CALL_LEASE_US;
    unlock_manager();
}

void call_manager_tick(void)
{
    lock_manager();
    bool expired = s_call_state != CALL_STATE_IDLE &&
                   esp_timer_get_time() >= s_call_lease_until_us;
    unlock_manager();
    if (expired) {
        ESP_LOGW(TAG, "Pi keepalive expired; ending call");
        end_call(true);
    }
}

/* Only Pi requests use these entry points. Reject stale mutations while active. */
bool call_manager_session_matches(uint32_t session) {
    return session != 0 && session == s_session && call_manager_is_active();
}
bool call_manager_bind_session(uint32_t session) {
    if (!session) return false;
    if (call_manager_is_active()) {
        if (session == s_session) {
            notify_pi_call_event(AUDIO_EVENT_CALL_STARTED, call_manager_get_origin(),
                                (uint8_t)call_manager_get_state());
        }
        return false; /* Duplicate START only replays its confirmation. */
    }
    if (session == s_session && s_session_ended) return false;
    s_session = session;
    s_ptt_request = 0;
    s_session_ended = false;
    return true;
}
bool call_manager_stop_session(uint32_t session) {
    if (call_manager_is_active() && !call_manager_session_matches(session)) return false;
    if (!call_manager_is_active() && session != s_session) {
        /* STOP for a lost START (or a pre-session journal) confirms idle only. */
        uint8_t payload[8] = {AUDIO_DATA_EVENT, AUDIO_EVENT_CALL_ENDED, 0, 0};
        put_session(payload+4, session);
        return send_frame_to_node(NODE_PI,SERVICE_AUDIO,CMD_DATA,payload,sizeof(payload));
    }
    return call_manager_end();
}

bool call_manager_voice_allowed(const protocol_frame_t *f) {
    if (f->service != SERVICE_AUDIO || f->command != CMD_DATA || !f->length ||
        f->payload[0] != AUDIO_DATA_CODEC2) return true;
    if (f->railing_id != RAILING_ID || f->length < AUDIO_CODEC2_META_SIZE ||
        f->payload[1] != CODEC2_MODE_2400 || f->payload[5] == 0 ||
        f->payload[5] > CODEC2_MAX_FRAMES_PER_PACKET || f->payload[6] != 6 ||
        f->length != AUDIO_CODEC2_META_SIZE + f->payload[5]*6) return false;
    uint32_t id=((uint32_t)f->payload[7]<<24)|((uint32_t)f->payload[8]<<16)|
                ((uint32_t)f->payload[9]<<8)|f->payload[10];
    lock_manager();
    bool valid=id && id==s_session &&
        ((s_call_state==CALL_STATE_FIELD_TX && f->payload[2]==AUDIO_DIRECTION_FIELD_TX &&
          f->src==NODE_S3 && f->dst==NODE_PI) ||
         (s_call_state==CALL_STATE_CONTROL_TX && f->payload[2]==AUDIO_DIRECTION_CONTROL_TX &&
          f->src==NODE_PI && f->dst==NODE_WROOM));
    unlock_manager();
    return valid;
}

bool call_manager_set_direction_ordered(uint32_t session, uint32_t request, audio_direction_t direction) {
    if (!call_manager_session_matches(session) || !request || request < s_ptt_request ||
        (direction != AUDIO_DIRECTION_FIELD_TX && direction != AUDIO_DIRECTION_CONTROL_TX)) return false;
    if (request == s_ptt_request && (uint8_t)call_manager_get_state() != (uint8_t)direction) return false;
    s_ptt_request = request;
    /* Same-ID retries replay downstream SET and Pi confirmation without changing generation. */
    return call_manager_set_direction(direction);
}
