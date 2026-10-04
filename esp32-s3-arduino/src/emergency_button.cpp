#include <Arduino.h>

#include "esp_system.h"

#include "board_config.h"
#include "protocol.h"
#include "ble_link.h"
#include "emergency_button.h"


// ============================================================
// STATE
// ============================================================

static bool
    s_button_down =
        false;


static bool
    s_emergency_active =
        false;


static uint32_t
    s_button_down_ms =
        0;


static uint32_t
    s_emergency_seq =
        1;


// ============================================================
// WRITE U32 BE
// ============================================================

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


// ============================================================
// SEND EMERGENCY
// ============================================================

static void send_emergency_event(void)
{
    protocol_frame_t frame =
        {};


    frame.railing_id =
        RAILING_ID;

    frame.src =
        NODE_S3;

    frame.dst =
        NODE_P4;

    frame.service =
        SERVICE_EMERGENCY;

    frame.command =
        CMD_START;

    frame.length =
        5;


    frame.payload[0] =
        EMERGENCY_SOURCE_BUTTON;


    write_u32_be(
        &frame.payload[1],
        s_emergency_seq
    );


    Serial.printf(
        "[EMERGENCY] BUTTON ACTIVE seq=%lu\n",
        (unsigned long)
            s_emergency_seq
    );


    if (
        ble_send_frame(
            &frame
        )
    )
    {
        s_emergency_seq++;


        if (
            s_emergency_seq ==
            0
        )
        {
            s_emergency_seq =
                1;
        }
    }
    else
    {
        Serial.println(
            "[EMERGENCY] BLE send failed"
        );
    }
}


// ============================================================
// INIT
// ============================================================

void emergency_button_init(void)
{
    /*
     * 외부 10k pull-down이 있으므로 INPUT.
     */
    pinMode(
        PIN_VOICE_CALL_BUTTON,
        INPUT
    );


    s_button_down =
        false;

    s_emergency_active =
        false;

    s_button_down_ms =
        0;


    s_emergency_seq =
        esp_random();


    if (
        s_emergency_seq ==
        0
    )
    {
        s_emergency_seq =
            1;
    }


    Serial.printf(
        "[EMERGENCY] Button GPIO=%d hold=%lu ms\n",
        PIN_VOICE_CALL_BUTTON,
        (unsigned long)
            EMERGENCY_HOLD_MS
    );
}


// ============================================================
// PROCESS
// ============================================================

void emergency_button_process(void)
{
    bool pressed =
        digitalRead(
            PIN_VOICE_CALL_BUTTON
        )
        ==
        HIGH;


    /*
     * 이미 비상상태가 latch 되었으면
     * 버튼을 다시 눌러도 추가 이벤트를 보내지 않는다.
     *
     * 관제 ACK가 들어와 clear될 때까지 유지.
     */
    if (
        s_emergency_active
    )
    {
        return;
    }


    uint32_t now =
        millis();


    /* ========================================================
     * BUTTON DOWN
     * ======================================================== */

    if (
        pressed
    )
    {
        if (
            !s_button_down
        )
        {
            s_button_down =
                true;

            s_button_down_ms =
                now;


            Serial.println(
                "[EMERGENCY] Button pressed"
            );
        }


        /*
         * 3초 이상 연속 HIGH
         */
        if (
            now -
            s_button_down_ms
            >=
            EMERGENCY_HOLD_MS
        )
        {
            s_emergency_active =
                true;


            Serial.println(
                "[EMERGENCY] 3 sec HOLD confirmed"
            );


            send_emergency_event();
        }


        return;
    }


    /* ========================================================
     * BUTTON RELEASE
     * ======================================================== */

    if (
        s_button_down
    )
    {
        uint32_t held =
            now -
            s_button_down_ms;


        if (
            held <
            EMERGENCY_HOLD_MS
        )
        {
            Serial.printf(
                "[EMERGENCY] Released early (%lu ms)\n",
                (unsigned long)held
            );
        }


        s_button_down =
            false;

        s_button_down_ms =
            0;
    }
}


// ============================================================
// STATE
// ============================================================

bool emergency_button_is_active(void)
{
    return
        s_emergency_active;
}


// ============================================================
// CLEAR
// ============================================================

void emergency_button_clear(void)
{
    s_emergency_active =
        false;

    s_button_down =
        false;

    s_button_down_ms =
        0;


    Serial.println(
        "[EMERGENCY] Cleared by ACK"
    );
}