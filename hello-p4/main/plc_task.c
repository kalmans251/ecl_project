#include "board_config.h"

#include "plc_uart.h"
#include "plc_task.h"

#include "protocol.h"
#include "protocol_parser.h"

#include "router.h"
#include "call_manager.h"
#include "esp_timer.h"
#include "esp_log.h"

static int64_t s_receive_until_us;
static int64_t s_last_grant_us;
static int64_t s_last_voice_us;
static unsigned s_voice_packets_since_grant;

_Static_assert(PLC_CONTROL_WINDOW_MS >= 20 && PLC_CONTROL_WINDOW_MS <= 200,
               "Pi accepts receive windows from 20 to 200 ms");
_Static_assert(PLC_VOICE_PACKETS_PER_GRANT > 0, "Grant cadence must be positive");

static bool send_complete_frame(const protocol_frame_t *frame)
{
    uint8_t buffer[PROTOCOL_MAX_FRAME_SIZE];
    int len = protocol_encode(frame, buffer, sizeof(buffer));
    if (len <= 0 || plc_uart_send(buffer, len) != len
        || !plc_uart_wait_tx_done(300)) {
        ESP_LOGW("PLC", "UART transmission failed; no control grant issued");
        return false;
    }
    return true;
}

static void grant_control_window(void)
{
    protocol_frame_t grant = {
        .railing_id = RAILING_ID,
        .src = NODE_P4, .dst = NODE_PI,
        .service = SERVICE_AUDIO, .command = CMD_DATA,
        .length = 3,
        .payload = {AUDIO_DATA_CONTROL_WINDOW,
                    PLC_CONTROL_WINDOW_MS >> 8, PLC_CONTROL_WINDOW_MS & 0xff}
    };
    send_complete_frame(&grant);
    // Preserve silence after an uncertain write as well; Pi will retry on
    // a later complete grant if this one did not make it across the modem.
    s_last_grant_us = esp_timer_get_time();
    s_receive_until_us = s_last_grant_us + PLC_CONTROL_WINDOW_MS * 1000;
    s_voice_packets_since_grant = 0;
}


/* ============================================================
 * PLC RX
 * ============================================================ */

static void handle_plc_frame(
    const protocol_frame_t *frame
)
{
    if (
        frame->railing_id !=
        RAILING_ID
    )
    {
        return;
    }


    xQueueSend(
        router_queue,
        frame,
        portMAX_DELAY
    );
}


/* ============================================================
 * PLC TX
 * ============================================================ */

static void process_plc_tx_queue(void)
{
    if (esp_timer_get_time() < s_receive_until_us) return;
    protocol_frame_t frame;


    while (
        xQueueReceive(
            plc_tx_queue,
            &frame,
            0
        ) == pdTRUE
    )
    {
        bool voice = frame.service == SERVICE_AUDIO && frame.command == CMD_DATA
            && frame.length > 0 && frame.payload[0] == AUDIO_DATA_CODEC2;
        if (voice && call_manager_get_state() != CALL_STATE_FIELD_TX) {
            // A direction change/stop invalidates audio already in the queue.
            continue;
        }
        if (!send_complete_frame(&frame)) {
            // Do not stream more bytes over a transmission that did not drain.
            s_receive_until_us = esp_timer_get_time() + PLC_CONTROL_WINDOW_MS * 1000;
            return;
        }
        if (voice) {
            s_last_voice_us = esp_timer_get_time();
            if (++s_voice_packets_since_grant >= PLC_VOICE_PACKETS_PER_GRANT) {
                grant_control_window();
            }
            // Yield even if the queue contains more voice or control events.
            return;
        }
    }
    // Keep controls possible if S3 has stopped producing audio during a call.
    if (call_manager_get_state() == CALL_STATE_FIELD_TX
        && esp_timer_get_time() - s_last_grant_us >= PLC_IDLE_GRANT_MS * 1000
        && esp_timer_get_time() - s_last_voice_us >= PLC_IDLE_GRANT_MS * 1000) {
        grant_control_window();
    }
    if (call_manager_get_state() != CALL_STATE_FIELD_TX) {
        s_voice_packets_since_grant = 0;
    }
}


/* ============================================================
 * PLC TASK
 * ============================================================ */

void plc_task(void *arg)
{
    uint8_t rx_buffer[256];

    protocol_parser_t parser;

    protocol_frame_t frame;


    protocol_parser_init(
        &parser
    );


    while (1)
    {
        int len =
            plc_uart_receive(
                rx_buffer,
                sizeof(rx_buffer)
            );


        if (len > 0)
        {
            for (
                int i = 0;
                i < len;
                i++
            )
            {
                bool complete =
                    protocol_parser_input(
                        &parser,
                        rx_buffer[i],
                        &frame
                    );


                if (complete)
                {
                    handle_plc_frame(
                        &frame
                    );
                }
            }
        }


        process_plc_tx_queue();
    }
}
