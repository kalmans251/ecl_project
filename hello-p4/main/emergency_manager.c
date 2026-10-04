#include "emergency_manager.h"

#include <string.h>

#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"

#include "esp_log.h"

#include "board_config.h"
#include "protocol.h"
#include "router.h"

#include "music_policy.h"
#include "call_manager.h"


static const char *TAG =
    "EMERGENCY";


static bool
    s_active =
        false;


static uint32_t
    s_active_seq =
        0;


static uint8_t
    s_source =
        0;


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
        (uint8_t)value;
}


/* ============================================================
 * SEND
 * ============================================================ */

static bool send_frame(
    uint8_t dst,
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
        dst;

    frame.service =
        SERVICE_EMERGENCY;

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
 * EVENT PAYLOAD
 *
 * [0]    source
 * [1..4] emergency seq
 * ============================================================ */

static void build_event_payload(
    uint8_t *payload,
    uint8_t source,
    uint32_t seq
)
{
    payload[0] =
        source;


    write_u32_be(
        &payload[1],
        seq
    );
}


/* ============================================================
 * INIT
 * ============================================================ */

void emergency_manager_init(void)
{
    s_active =
        false;

    s_active_seq =
        0;

    s_source =
        0;


    ESP_LOGI(
        TAG,
        "Emergency manager initialized"
    );
}


/* ============================================================
 * START
 * ============================================================ */

bool emergency_manager_start(
    uint8_t source,
    uint32_t seq
)
{
    /*
     * 동일 프레임 재전송.
     */
    if (
        s_active
    )
    {
        if (
            s_active_seq ==
            seq
        )
        {
            ESP_LOGW(
                TAG,
                "Duplicate START seq=%lu",
                (unsigned long)seq
            );


            return true;
        }


        ESP_LOGW(
            TAG,
            "Emergency already active seq=%lu",
            (unsigned long)
                s_active_seq
        );


        return false;
    }


    s_active =
        true;

    s_active_seq =
        seq;

    s_source =
        source;


    /*
     * 일반 음악 일시정지.
     *
     * 비상 해제 시 같은 위치에서 RESUME 가능.
     */
    music_policy_add_pause_reason(
        MUSIC_PAUSE_REASON_EMERGENCY
    );


    uint8_t payload[5];


    build_event_payload(
        payload,
        source,
        seq
    );


    /*
     * WROOM:
     * 현장 비상음 시작.
     */
    send_frame(
        NODE_WROOM,
        CMD_START,
        payload,
        sizeof(payload)
    );


    /*
     * Raspberry Pi:
     * 관제 비상상태 시작.
     */
    send_frame(
        NODE_PI,
        CMD_START,
        payload,
        sizeof(payload)
    );


    ESP_LOGW(
        TAG,
        "EMERGENCY START source=%u seq=%lu",
        source,
        (unsigned long)seq
    );


    return true;
}


/* ============================================================
 * FIELD CANCEL
 *
 * 현장 버튼을 다시 3초 누름.
 * ============================================================ */

bool emergency_manager_cancel(
    uint8_t source,
    uint32_t seq
)
{
    if (
        !s_active
    )
    {
        ESP_LOGW(
            TAG,
            "CANCEL ignored: no active emergency"
        );


        return false;
    }


    if (
        seq !=
        s_active_seq
    )
    {
        ESP_LOGW(
            TAG,
            "CANCEL seq mismatch active=%lu rx=%lu",
            (unsigned long)
                s_active_seq,
            (unsigned long)
                seq
        );


        return false;
    }


    uint8_t payload[5];


    build_event_payload(
        payload,
        source,
        seq
    );


    /*
     * 현장 비상음 종료.
     */
    send_frame(
        NODE_WROOM,
        CMD_STOP,
        payload,
        sizeof(payload)
    );


    /*
     * Pi / 관제에도 전체 비상 취소 전달.
     */
    send_frame(
        NODE_PI,
        CMD_STOP,
        payload,
        sizeof(payload)
    );


    /*
     * 일반 음악 복구.
     *
     * CALL/LED/USER 등 다른 pause reason이 있으면
     * 실제 RESUME은 하지 않는다.
     */
    music_policy_remove_pause_reason(
        MUSIC_PAUSE_REASON_EMERGENCY
    );


    s_active =
        false;

    s_active_seq =
        0;

    s_source =
        0;


    ESP_LOGI(
        TAG,
        "EMERGENCY CANCEL seq=%lu",
        (unsigned long)seq
    );


    return true;
}


/* ============================================================
 * CONTROL ACK
 *
 * 관제 확인 버튼:
 *
 * 비상음 종료
 * ->
 * CALL 시작
 * ->
 * FIELD_TX
 * ============================================================ */

bool emergency_manager_ack(
    uint32_t seq
)
{
    if (
        !s_active
    )
    {
        ESP_LOGW(
            TAG,
            "ACK ignored: no active emergency"
        );


        return false;
    }


    if (
        seq !=
        s_active_seq
    )
    {
        ESP_LOGW(
            TAG,
            "ACK seq mismatch active=%lu rx=%lu",
            (unsigned long)
                s_active_seq,
            (unsigned long)
                seq
        );


        return false;
    }


    uint8_t event_payload[5];


    build_event_payload(
        event_payload,
        s_source,
        seq
    );


    /*
     * 비상음 우선 종료.
     */
    send_frame(
        NODE_WROOM,
        CMD_STOP,
        event_payload,
        sizeof(event_payload)
    );


    /*
     * 통화 시작.
     *
     * call_manager 내부에서 CALL pause reason을 추가하므로
     * 일반 음악이 중간에 재생되지 않는다.
     */
    if (
        !call_manager_start(
            CALL_ORIGIN_EMERGENCY
        )
    )
    {
        /*
         * 통화 시작 실패라면
         * 비상음을 다시 시작.
         */
        send_frame(
            NODE_WROOM,
            CMD_START,
            event_payload,
            sizeof(event_payload)
        );


        ESP_LOGE(
            TAG,
            "Emergency call start failed"
        );


        return false;
    }


    /*
     * S3의 emergency latch 해제.
     *
     * payload:
     *
     * [0] ACK
     * [1..4] seq
     */
    uint8_t ack_payload[5];


    ack_payload[0] =
        EMERGENCY_ACTION_ACK;


    write_u32_be(
        &ack_payload[1],
        seq
    );


    send_frame(
        NODE_S3,
        CMD_SET,
        ack_payload,
        sizeof(ack_payload)
    );


    /*
     * CALL reason이 이미 걸렸으므로
     * EMERGENCY reason 제거.
     */
    music_policy_remove_pause_reason(
        MUSIC_PAUSE_REASON_EMERGENCY
    );


    s_active =
        false;

    s_active_seq =
        0;

    s_source =
        0;


    ESP_LOGI(
        TAG,
        "EMERGENCY ACK -> CALL FIELD_TX seq=%lu",
        (unsigned long)seq
    );


    return true;
}


/* ============================================================
 * GET
 * ============================================================ */

bool emergency_manager_is_active(void)
{
    return
        s_active;
}


uint32_t emergency_manager_get_seq(void)
{
    return
        s_active_seq;
}


uint8_t emergency_manager_get_source(void)
{
    return
        s_source;
}