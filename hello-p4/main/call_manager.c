#include <string.h>

#include "call_manager.h"
#include "emergency_manager.h"

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

/* Controller-owned preparation transaction. Voice readers use s_mutex. */
static uint8_t s_operation, s_target, s_ready_mask, s_failed_node, s_failed_reason;
static bool s_preparing;
static bool s_health_pending, s_fault_stopping;
static uint32_t s_health_token;
static uint8_t s_health_mask;
static int64_t s_health_due, s_health_deadline, s_health_retry;
static void handle_health(const protocol_frame_t *f);
static int64_t s_prepare_deadline, s_next_probe;
/* Pi waits at least 1 s after a call command. Leave time for the 200 ms
 * receive grant and modem delivery; never emit a late unsolicited reply. */
#define CALL_FIRST_REPLY_US 700000
static int64_t s_first_reply_until;
static bool s_stop_polled_only;
static bool end_call(bool polled_only);
static void lock_manager(void);
static void unlock_manager(void);
static void begin_prepare(uint8_t operation, uint8_t direction) {
    lock_manager();
    s_health_pending=false;
    s_operation=operation;s_target=direction;s_ready_mask=0;
    s_failed_node=s_failed_reason=0;s_preparing=true;
    s_prepare_deadline=esp_timer_get_time()+4000000;
    s_first_reply_until=esp_timer_get_time()+CALL_FIRST_REPLY_US;
    s_next_probe=esp_timer_get_time()+200000;
    unlock_manager();
}
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
    s_preparing = false;


    s_call_origin =
        CALL_ORIGIN_NORMAL;
    s_call_lease_until_us = esp_timer_get_time() + CALL_LEASE_US;
    s_last_end_origin = CALL_ORIGIN_NORMAL;
    s_session = 0;
    s_ptt_request = 0;
    s_session_ended = false;
    s_operation=0;s_preparing=false;s_ready_mask=0;s_failed_node=0;
    s_health_pending=false;s_fault_stopping=false;s_health_token=0;s_health_due=0;


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

    s_fault_stopping=false;
    begin_prepare(CMD_START,AUDIO_DIRECTION_FIELD_TX);
    request_audio_start();

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

static void notify_prepare_failure(void) {
    uint8_t payload[14]={AUDIO_DATA_EVENT,AUDIO_EVENT_PREPARATION_FAILED,(uint8_t)s_call_origin,s_target};
    put_session(payload+4,s_session);put_session(payload+8,s_operation==CMD_SET?s_ptt_request:0);
    payload[12]=s_failed_node;payload[13]=s_failed_reason;
    send_frame_to_node(NODE_PI,SERVICE_AUDIO,CMD_DATA,payload,sizeof(payload));
}
static bool finish_prepare(void) {
    if(s_failed_node){notify_prepare_failure();return false;}
    if(s_ready_mask!=3)return false;
    lock_manager();
    if(s_operation!=CMD_STOP){
        s_preparing=false;
        s_call_state=(call_state_t)s_target;
        s_health_due=esp_timer_get_time()+1000000;
    }
    unlock_manager();
    return true;
}
bool call_manager_set_direction(audio_direction_t direction) {
    if(!call_manager_is_active() || (direction!=AUDIO_DIRECTION_FIELD_TX &&
        direction!=AUDIO_DIRECTION_CONTROL_TX))return false;
    begin_prepare(CMD_SET,direction);
    request_audio_direction(direction);
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

static bool finalize_end(bool polled_only)
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

    /* Endpoints have acknowledged stop before restoring music. */

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
    s_fault_stopping=false;
    s_health_pending=false;

    s_call_state =
        CALL_STATE_IDLE;
    s_preparing = false;


    s_call_origin =
        CALL_ORIGIN_NORMAL;


    memset(
        &s_restore,
        0,
        sizeof(s_restore)
    );


    unlock_manager();


    if (origin==CALL_ORIGIN_EMERGENCY) emergency_manager_call_ended();
    notify_call_end(origin, polled_only);


    ESP_LOGI(
        TAG,
        "CALL END origin=%d -> IDLE",
        origin
    );


    return true;
}


static bool end_call(bool polled_only) {
    if(!call_manager_is_active())return finalize_end(polled_only);
    if(s_operation!=CMD_STOP) {
        begin_prepare(CMD_STOP,0);
        s_stop_polled_only=polled_only;
        request_audio_stop();
        return true;
    }
    if(polled_only && s_failed_node)return false;
    if(!finish_prepare())return false;
    return finalize_end(polled_only);
}

void call_manager_handle_readiness(const protocol_frame_t *f) {
    if(f->length && f->payload[0]==AUDIO_DATA_HEALTH){handle_health(f);return;}
    if(f->railing_id!=RAILING_ID || f->dst!=NODE_P4 || f->service!=SERVICE_AUDIO ||
       f->command!=CMD_DATA || f->length!=12 || f->payload[0]!=AUDIO_DATA_READY ||
       (f->src!=NODE_WROOM && f->src!=NODE_S3) || !s_preparing)return;
    uint8_t session[4],request[4];put_session(session,s_session);
    put_session(request,s_operation==CMD_SET?s_ptt_request:0);
    if(f->payload[1]!=s_operation || f->payload[2]!=s_target ||
       memcmp(f->payload+4,session,4) || memcmp(f->payload+8,request,4) || f->payload[3]>2)return;
    uint8_t bit=f->src==NODE_WROOM?1:2;
    if(f->payload[3]==1){
        s_ready_mask|=bit;
        if(s_operation==CMD_STOP && s_ready_mask==3)s_failed_node=s_failed_reason=0;
    }
    if(f->payload[3]==2){s_failed_node=f->src;s_failed_reason=2;}
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
    if (s_call_state != CALL_STATE_IDLE && s_operation!=CMD_STOP && esp_timer_get_time() < s_call_lease_until_us)
        s_call_lease_until_us = esp_timer_get_time() + CALL_LEASE_US;
    unlock_manager();
}

static void endpoint_failed(uint8_t node, uint8_t reason) {
    protocol_frame_t f={.railing_id=RAILING_ID,.src=NODE_P4,.dst=NODE_PI,
        .service=SERVICE_AUDIO,.command=CMD_DATA,.length=10,
        .payload={AUDIO_DATA_EVENT,AUDIO_EVENT_ENDPOINT_FAILED,(uint8_t)s_call_origin,0}};
    put_session(f.payload+4,s_session);f.payload[8]=node;f.payload[9]=reason;
    ESP_LOGW(TAG,"Call endpoint failed node=%u reason=%u; stopping",node,reason);
    s_fault_stopping=true;
    end_call(true); /* sets preparing before any further voice can be routed */
    event_outbox_store_call_fault(&f);
}
static void handle_health(const protocol_frame_t *f) {
    if(!s_health_pending || s_preparing || !call_manager_is_active() ||
       f->railing_id!=RAILING_ID || f->dst!=NODE_P4 || f->service!=SERVICE_AUDIO ||
       f->command!=CMD_DATA || f->length!=16 ||
       (f->src!=NODE_WROOM && f->src!=NODE_S3) || f->payload[1]!=CMD_SET ||
       f->payload[2]!=s_target || f->payload[3]>2)return;
    uint8_t expected[12];put_session(expected,s_session);put_session(expected+4,s_ptt_request);
    put_session(expected+8,s_health_token);
    if(memcmp(f->payload+4,expected,sizeof(expected)))return;
    if(f->payload[3]!=1){endpoint_failed(f->src,2);return;}
    s_health_mask|=f->src==NODE_WROOM?1:2;
    if(s_health_mask==3){s_health_pending=false;s_health_due=esp_timer_get_time()+1000000;}
}
static void health_tick(int64_t now) {
    if(s_preparing || !call_manager_is_active())return;
    if(s_health_pending) {
        if(now>=s_health_deadline){endpoint_failed((s_health_mask&1)?NODE_S3:NODE_WROOM,3);return;}
        if(now<s_health_retry)return;
    } else {
        if(now<s_health_due)return;
        if(++s_health_token==0)++s_health_token;
        s_health_mask=0;s_health_pending=true;s_health_deadline=now+3000000;
    }
    s_health_retry=now+500000;
    uint8_t payload[13]={(uint8_t)s_target};
    put_session(payload+1,s_session);put_session(payload+5,s_ptt_request);
    put_session(payload+9,s_health_token);
    if(!(s_health_mask&1))send_frame_to_node(NODE_WROOM,SERVICE_AUDIO,CMD_CALL_HEALTH,payload,sizeof(payload));
    if(!(s_health_mask&2))send_frame_to_node(NODE_S3,SERVICE_AUDIO,CMD_CALL_HEALTH,payload,sizeof(payload));
}
void call_manager_tick(void)
{
    int64_t now=esp_timer_get_time();
    health_tick(now);
    /* Complete the original request as soon as BOTH endpoints are ready.
     * Previously only a duplicate Pi command called finish_prepare(), making
     * every successful operation wait for a timeout and retransmission.
     * Autonomous fault/lease stops remain outbox-only on the shared bus. */
    if(s_preparing && s_ready_mask==3 && !s_failed_node) {
        if(s_operation==CMD_STOP && s_stop_polled_only) {
            end_call(true);
        } else if(now < s_first_reply_until && now < s_call_lease_until_us) {
            if(s_operation==CMD_STOP)end_call(false);
            else if(finish_prepare()) {
                notify_pi_call_event(s_operation==CMD_START ? AUDIO_EVENT_CALL_STARTED :
                                     AUDIO_EVENT_DIRECTION_CHANGED,s_call_origin,s_target);
            }
        }
    }
    if(s_preparing && s_ready_mask!=3 && !s_failed_node && now>=s_prepare_deadline) {
        s_failed_node=(s_ready_mask&1)?NODE_S3:NODE_WROOM;s_failed_reason=3;
    }
    if(s_preparing && now>=s_next_probe) {
        s_next_probe=now+(s_failed_node?1000000:200000);
        if(s_operation==CMD_START)request_audio_start();
        else if(s_operation==CMD_SET)request_audio_direction((audio_direction_t)s_target);
        else if(s_operation==CMD_STOP)request_audio_stop();
    }
    lock_manager();
    bool expired = s_call_state != CALL_STATE_IDLE &&
                   esp_timer_get_time() >= s_call_lease_until_us;
    unlock_manager();
    if (expired) {
        if(s_operation!=CMD_STOP)ESP_LOGW(TAG, "Pi keepalive expired; ending call");
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
        if (session == s_session && s_operation==CMD_START && finish_prepare()) {
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
    if (call_manager_is_active() && session != s_session) return false;
    if (!call_manager_is_active() && (!s_session_ended || session != s_session)) {
        /* After a P4 reboot, endpoints may still hold the recovered session.
         * Confirm their physical stop before declaring the bus free. */
        lock_manager();
        s_session=session;s_ptt_request=0;s_operation=0;
        s_call_state=CALL_STATE_FIELD_TX;s_preparing=true;
        s_call_lease_until_us=esp_timer_get_time()+CALL_LEASE_US;
        unlock_manager();
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
    bool valid=!s_preparing && id && id==s_session &&
        ((s_call_state==CALL_STATE_FIELD_TX && f->payload[2]==AUDIO_DIRECTION_FIELD_TX &&
          f->src==NODE_S3 && f->dst==NODE_PI) ||
         (s_call_state==CALL_STATE_CONTROL_TX && f->payload[2]==AUDIO_DIRECTION_CONTROL_TX &&
          f->src==NODE_PI && f->dst==NODE_WROOM));
    unlock_manager();
    return valid;
}

bool call_manager_set_direction_ordered(uint32_t session, uint32_t request, audio_direction_t direction) {
    if(!call_manager_session_matches(session) || !request || request<s_ptt_request ||
       (direction!=AUDIO_DIRECTION_FIELD_TX && direction!=AUDIO_DIRECTION_CONTROL_TX) ||
       s_operation==CMD_STOP)return false;
    if(request==s_ptt_request) {
        if(s_operation!=CMD_SET || direction!=s_target)return false;
        if(finish_prepare())notify_pi_call_event(AUDIO_EVENT_DIRECTION_CHANGED,s_call_origin,direction);
        return true;
    }
    if(s_preparing)return false;
    s_ptt_request=request;
    return call_manager_set_direction(direction);
}

bool call_manager_control_grants_enabled(void) {
    lock_manager();
    bool enabled=s_call_state!=CALL_STATE_IDLE &&
        (s_call_state==CALL_STATE_FIELD_TX || (s_preparing && !s_fault_stopping));
    /* During a CONTROL_TX fault Pi still owns TX until it polls the fault.
     * Do not inject grants into that stream; unknown Pi uses lease recovery. */
    unlock_manager();
    return enabled;
}
