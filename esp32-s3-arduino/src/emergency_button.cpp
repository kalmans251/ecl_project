#include <Arduino.h>

#include "esp_system.h"

#include "board_config.h"
#include "protocol.h"
#include "ble_link.h"
#include "emergency_button.h"

// ============================================================
// PRIVATE FUNCTION PROTOTYPES
// ============================================================

static void send_emergency_start(void);

static void send_emergency_cancel(void);

static void handle_long_press(void);
static void emergency_button_retry_frame(protocol_frame_t *);
static uint8_t s_pending_command;
static unsigned s_attempts;
static uint32_t s_last_attempt;
static void transmit_pending(void) {
    if (!s_pending_command || s_attempts >= 6 || !ble_link_is_connected()) return;
    protocol_frame_t f = {};
    f.railing_id=RAILING_ID; f.src=NODE_S3; f.dst=NODE_P4;
    f.service=SERVICE_EMERGENCY; f.command=s_pending_command; f.length=5;
    f.payload[0]=EMERGENCY_SOURCE_BUTTON;
    // Filled below by the sender, after the event sequence is reserved.
    emergency_button_retry_frame(&f);
    ble_send_frame(&f);
    s_last_attempt=millis(); ++s_attempts;
    if (s_attempts==6) Serial.println("[EMERGENCY] Confirmation pending; hold again to retry cancel");
}


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


static bool
    s_raw_pressed =
        false;


static uint32_t
    s_raw_changed_ms =
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
// INIT
// ============================================================

void emergency_button_init(void)
{
    s_active_emergency_seq=0; s_pending_command=0; s_attempts=0; s_long_press_consumed=false;
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

    s_raw_pressed =
        false;

    s_raw_changed_ms =
        millis();


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
    if (s_pending_command && millis()-s_last_attempt >= 1000) transmit_pending();
    bool raw_pressed =
        digitalRead(
            PIN_VOICE_CALL_BUTTON
        )
        ==
        HIGH;


    uint32_t now =
        millis();


    /*
     * 50 ms debounce.
     *
     * Long wiring / noise previously produced repeated
     * 1 ms press/release events. Only a level that remains
     * stable for EMERGENCY_DEBOUNCE_MS is accepted.
     */
    if (
        raw_pressed !=
        s_raw_pressed
    )
    {
        s_raw_pressed =
            raw_pressed;

        s_raw_changed_ms =
            now;

        return;
    }


    if (
        now -
        s_raw_changed_ms
        <
        EMERGENCY_DEBOUNCE_MS
    )
    {
        return;
    }


    bool pressed =
        s_raw_pressed;


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


static void emergency_button_retry_frame(protocol_frame_t *f) {
    write_u32_be(f->payload+1,s_active_emergency_seq);
}
static void send_emergency_start(void) {
    s_active_emergency_seq=s_emergency_seq++;
    if (!s_emergency_seq) s_emergency_seq=1;
    s_pending_command=CMD_START; s_attempts=0;
    transmit_pending();
}
static void send_emergency_cancel(void) {
    s_pending_command=CMD_STOP; s_attempts=0;
    transmit_pending();
}
void emergency_button_confirm(uint8_t state, uint32_t seq) {
    if (!s_active_emergency_seq || seq!=s_active_emergency_seq) return;
    if (state==0x82) {
        s_emergency_active=false; s_active_emergency_seq=0; s_pending_command=0;
        Serial.println("[EMERGENCY] END confirmed");
    } else if (state==0x80 || state==0x81) {
        s_emergency_active=true;
        if (s_pending_command==CMD_START) s_pending_command=0;
        Serial.println("[EMERGENCY] START/CALL confirmed");
    }
}
static void handle_long_press(void) {
    if (s_active_emergency_seq) { send_emergency_cancel(); return; }
    send_emergency_start();
}
