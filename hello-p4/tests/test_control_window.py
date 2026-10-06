"""Run the actual PLC task/protocol on a host with simulated UART/time/queues.

python -m unittest discover -s hello-p4/tests -v
This exercises scheduling; it is not a replacement for an ESP-IDF build.
"""
from pathlib import Path
import subprocess
import tempfile
import unittest


MAIN = Path(__file__).resolve().parents[1] / "main"
HEADERS = {
    "driver/uart.h": "#pragma once\n",
    "driver/gpio.h": "#pragma once\n",
    "freertos/FreeRTOS.h": """
        #pragma once
        #include <stdint.h>
        typedef void *QueueHandle_t;
        typedef unsigned TickType_t;
        #define pdTRUE 1
        #define portMAX_DELAY 0xffffffffu
        #define pdMS_TO_TICKS(ms) (ms)
    """,
    "freertos/queue.h": """
        #pragma once
        #include "FreeRTOS.h"
        int xQueueReceive(QueueHandle_t, void *, TickType_t);
        int xQueueSend(QueueHandle_t, const void *, TickType_t);
    """,
    "esp_timer.h": "#include <stdint.h>\nint64_t esp_timer_get_time(void);\n",
    "esp_log.h": '#define ESP_LOGW(tag, ...) ((void)0)\n#define ESP_LOGI(tag, ...) ((void)0)\n',
}

HARNESS = r"""
#include <assert.h>
#include <string.h>
#include <stdio.h>
#include "plc_task.c"

QueueHandle_t router_queue = (void *)1;
QueueHandle_t plc_tx_queue = (void *)2;
QueueHandle_t wroom_tx_queue;
QueueHandle_t p4_controller_queue;
static protocol_frame_t queue[16], sent[32];
static unsigned count, index_, sent_count, drained;
static int64_t now;
static call_state_t mode;
static bool drain_ok;

int64_t esp_timer_get_time(void) { return now; }
call_state_t call_manager_get_state(void) { return mode; }
int xQueueReceive(QueueHandle_t q, void *out, TickType_t timeout) {
    (void)timeout;
    assert(q == plc_tx_queue);
    if (index_ == count) return 0;
    memcpy(out, &queue[index_++], sizeof(protocol_frame_t));
    return pdTRUE;
}
int xQueueSend(QueueHandle_t q, const void *in, TickType_t timeout) {
    (void)q; (void)in; (void)timeout; return pdTRUE;
}
int plc_uart_send(const uint8_t *bytes, size_t len) {
    assert(sent_count < 32);
    assert(protocol_decode(bytes, len, &sent[sent_count++]) == (int)len);
    now += (int64_t)len * 10 * 1000000 / PLC_BAUD_RATE;
    return (int)len;
}
bool plc_uart_wait_tx_done(uint32_t timeout) {
    assert(timeout == 300); drained++; return drain_ok;
}
int plc_uart_receive(uint8_t *buffer, size_t len) {
    (void)buffer; (void)len; return 0;
}
static void reset(void) {
    count = index_ = sent_count = drained = 0;
    now = 0; mode = CALL_STATE_FIELD_TX; drain_ok = true;
    s_receive_until_us = s_last_grant_us = s_last_voice_us = s_end_tx_quiet_until_us = 0;
    s_voice_packets_since_grant = 0;
}
static protocol_frame_t voice(void) {
    protocol_frame_t f = {.railing_id=1, .src=NODE_S3, .dst=NODE_PI,
        .service=SERVICE_AUDIO, .command=CMD_DATA, .length=55};
    f.payload[0] = AUDIO_DATA_CODEC2;
    return f;
}
static protocol_frame_t event(void) {
    protocol_frame_t f = {.railing_id=1, .src=NODE_P4, .dst=NODE_PI,
        .service=SERVICE_AUDIO, .command=CMD_DATA, .length=4};
    f.payload[0] = AUDIO_DATA_EVENT;
    return f;
}
int main(void) {
    reset();
    for (unsigned i = 0; i < PLC_VOICE_PACKETS_PER_GRANT + 1; ++i)
        queue[count++] = voice();
    queue[count++] = event();
    for (unsigned i = 1; i <= PLC_VOICE_PACKETS_PER_GRANT; ++i) {
        process_plc_tx_queue();
        assert(index_ == i);
        assert(sent_count == i + (i == PLC_VOICE_PACKETS_PER_GRANT));
    }
    unsigned grant_index = PLC_VOICE_PACKETS_PER_GRANT;
    assert(drained == sent_count);
    assert(sent[0].payload[0] == AUDIO_DATA_CODEC2);
    assert(sent[grant_index].payload[0] == AUDIO_DATA_CONTROL_WINDOW);
    assert(sent[grant_index].payload[2] == PLC_CONTROL_WINDOW_MS);
    assert(s_receive_until_us - now == PLC_CONTROL_WINDOW_MS * 1000);
    now = s_receive_until_us - 1;
    process_plc_tx_queue();
    assert(sent_count == grant_index + 1);
    mode = CALL_STATE_CONTROL_TX;
    now = s_receive_until_us;
    process_plc_tx_queue();
    assert(sent_count == grant_index + 2 && index_ == count);
    assert(sent[grant_index + 1].payload[0] == AUDIO_DATA_EVENT);

    reset();
    now = PLC_IDLE_GRANT_MS * 1000;
    process_plc_tx_queue();
    assert(sent_count == 1 && sent[0].payload[0] == AUDIO_DATA_CONTROL_WINDOW);
    process_plc_tx_queue(); assert(sent_count == 1);

    reset(); mode = CALL_STATE_IDLE; queue[count++] = voice();
    process_plc_tx_queue(); assert(sent_count == 0);

    reset();mode=CALL_STATE_IDLE;now=PLC_IDLE_GRANT_MS*1000;
    process_plc_tx_queue();assert(sent_count==0);
    now+=8000000;process_plc_tx_queue();assert(sent_count==0);

    reset(); mode=CALL_STATE_IDLE; now=PLC_IDLE_GRANT_MS*1000;
    queue[count++]=event();queue[0].payload[1]=AUDIO_EVENT_CALL_ENDED;
    queue[0].payload[3]=0;
    process_plc_tx_queue();
    assert(sent_count==1 && sent[0].payload[1]==AUDIO_EVENT_CALL_ENDED);
    int64_t end_drained=now;
    now=end_drained+PLC_END_TX_QUIET_MS*1000-1;
    process_plc_tx_queue();assert(sent_count==1);
    now=end_drained+PLC_END_TX_QUIET_MS*1000;
    process_plc_tx_queue();assert(sent_count==1);
    queue[count++]=event();process_plc_tx_queue();assert(sent_count==2);

    reset(); drain_ok = false; queue[count++] = voice(); queue[count++] = voice();
    process_plc_tx_queue();
    assert(sent_count == 1 && index_ == 1); // no grant before a successful drain
    assert(s_receive_until_us > now);

    reset(); now = PLC_IDLE_GRANT_MS * 1000; drain_ok = false;
    process_plc_tx_queue(); assert(s_receive_until_us > now);
    puts("P4 UART drain, receive-window silence, idle grants and stale voice: PASS");
    return 0;
}
"""


class P4ControlWindowTests(unittest.TestCase):
    def test_scheduler(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name, body in HEADERS.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(body)
            source = root / "harness.c"
            source.write_text(HARNESS)
            binary = root / "harness"
            subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror",
                            "-Wno-unused-parameter", "-I", str(root), "-I", str(MAIN),
                            str(source), str(MAIN / "protocol.c"),
                            str(MAIN / "protocol_parser.c"), "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True)
