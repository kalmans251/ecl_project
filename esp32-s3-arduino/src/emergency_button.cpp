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

        
static bool
    s_long_press_consumed =
        false;

static uint32_t
    s_active_emergency_seq =
        0;
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


    uint32_t now =
        millis();


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

            s_long_press_consumed =
                false;

            s_button_down_ms =
                now;


            Serial.println(
                "[EMERGENCY] Button pressed"
            );
        }


        /*
         * 한 번 누르고 계속 6초, 9초 유지해도
         * START -> STOP이 연속 발생하지 않게 함.
         */
        if (
            s_long_press_consumed
        )
        {
            return;
        }


        if (
            now -
            s_button_down_ms
            >=
            EMERGENCY_HOLD_MS
        )
        {
            s_long_press_consumed =
                true;

            handle_long_press();
        }


        return;
    }


    if (
        s_button_down
    )
    {
        Serial.printf(
            "[EMERGENCY] Button released held=%lu ms\n",
            (unsigned long)(
                now -
                s_button_down_ms
            )
        );
    }


    s_button_down =
        false;

    s_long_press_consumed =
        false;
        
    s_active_emergency_seq =
        0;
        
    s_button_down_ms =
        0;
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

static void send_emergency_start(void)
{
    s_active_emergency_seq =
        s_emergency_seq;


    protocol_frame_t frame = {};

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
        s_active_emergency_seq
    );


    ble_send_frame(
        &frame
    );


    Serial.printf(
        "[EMERGENCY] START seq=%lu\n",
        (unsigned long)
            s_active_emergency_seq
    );


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

static void send_emergency_cancel(void)
{
    protocol_frame_t frame = {};

    frame.railing_id =
        RAILING_ID;

    frame.src =
        NODE_S3;

    frame.dst =
        NODE_P4;

    frame.service =
        SERVICE_EMERGENCY;

    frame.command =
        CMD_STOP;

    frame.length =
        5;

    frame.payload[0] =
        EMERGENCY_SOURCE_BUTTON;


    write_u32_be(
        &frame.payload[1],
        s_active_emergency_seq
    );


    ble_send_frame(
        &frame
    );


    Serial.printf(
        "[EMERGENCY] CANCEL seq=%lu\n",
        (unsigned long)
            s_active_emergency_seq
    );


    s_active_emergency_seq =
        0;
}

static void handle_long_press(void)
{
    if (
        !s_emergency_active
    )
    {
        s_emergency_active =
            true;

        send_emergency_start();

        return;
    }


    s_emergency_active =
        false;

    send_emergency_cancel();
}