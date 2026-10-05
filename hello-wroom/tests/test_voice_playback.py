"""Actual WROOM session/worker C with host UART/I2S/RTOS substitutes."""
from pathlib import Path
import subprocess
import tempfile
import unittest
import ctypes.util
import os

CODEC2_LIB = os.environ.get('ECL_TEST_CODEC2_LIB') or ctypes.util.find_library('codec2')
MAIN = Path(__file__).resolve().parents[1] / 'main'
HEADERS = {
'freertos/FreeRTOS.h': '''#pragma once
#include <stdint.h>
typedef void *QueueHandle_t;
typedef void *TaskHandle_t;
typedef unsigned TickType_t;
typedef int portMUX_TYPE;
#define portMUX_INITIALIZER_UNLOCKED 0
#define portENTER_CRITICAL(x) ((void)(x))
#define portEXIT_CRITICAL(x) ((void)(x))
#define pdTRUE 1
#define pdPASS 1
#define pdMS_TO_TICKS(x) (x)
''',
'freertos/task.h': '''#pragma once
#include "FreeRTOS.h"
int xTaskCreate(void (*)(void *), const char *, unsigned, void *, unsigned, TaskHandle_t *);
void vTaskDelay(unsigned);
''',
'freertos/queue.h': '''#pragma once
#include "FreeRTOS.h"
QueueHandle_t xQueueCreate(unsigned, unsigned);
int xQueueReceive(QueueHandle_t, void *, unsigned);
int xQueueSend(QueueHandle_t, const void *, unsigned);
int xQueueReset(QueueHandle_t);
unsigned uxQueueMessagesWaiting(QueueHandle_t);
''',
'esp_log.h': '''#define ESP_LOGI(tag, ...) ((void)(tag))
#define ESP_LOGW(tag, ...) ((void)(tag))
#define ESP_LOGE(tag, ...) ((void)(tag))
''',
'codec2.h': '''struct CODEC2;
#define CODEC2_MODE_2400 1
struct CODEC2 *codec2_create(int);
void codec2_destroy(struct CODEC2 *);
int codec2_samples_per_frame(struct CODEC2 *);
int codec2_bits_per_frame(struct CODEC2 *);
void codec2_decode(struct CODEC2 *, short *, const unsigned char *);
''',
}
HARNESS = r'''
#include <assert.h>
#include <setjmp.h>
#include <stdio.h>
#include "voice_session.c"
static jmp_buf finished;
static voice_packet_t queued[12];
static unsigned count, index_, writes, released;
static bool music_playing, music_paused;
static uint32_t restored_rate;
static void (*worker)(void *);
QueueHandle_t xQueueCreate(unsigned n, unsigned size) { assert(n==12 && size==sizeof(voice_packet_t)); return (void *)1; }
int xTaskCreate(void (*fn)(void *), const char *name, unsigned stack, void *arg, unsigned priority, TaskHandle_t *handle) {
    (void)name; assert(stack==32768); (void)arg; (void)priority; worker=fn; *handle=(void *)1; return pdPASS;
}
void vTaskDelay(unsigned ticks) { (void)ticks; }
int xQueueSend(QueueHandle_t q, const void *p, unsigned ticks) {
    (void)q; (void)ticks;
    if (count == 12) return 0;
    memcpy(&queued[count++], p, sizeof(voice_packet_t)); return pdTRUE;
}
int xQueueReset(QueueHandle_t q) { (void)q; count=index_=0; return pdTRUE; }
unsigned uxQueueMessagesWaiting(QueueHandle_t q) { (void)q; return count-index_; }
int xQueueReceive(QueueHandle_t q, void *p, unsigned ticks) {
    (void)q; (void)ticks;
    if (released) longjmp(finished, 1);
    if (index_==count) return 0;
    memcpy(p, &queued[index_++], sizeof(voice_packet_t)); return pdTRUE;
}
bool music_player_pause(void) { music_paused=music_playing; return true; }
bool music_player_is_playing(void) { return music_playing; }
bool music_player_is_paused(void) { return music_paused; }
uint32_t audio_output_get_sample_rate(void) { return music_playing ? 44100 : 0; }
bool audio_output_set_sample_rate(uint32_t rate) { restored_rate=rate; return true; }
bool emergency_alert_stop(void) { return true; }
bool emergency_alert_is_active(void) { return false; }
bool audio_output_claim(void) { return true; }
void audio_output_release(void) { ++released; }
void audio_output_deinit(void) {}
bool audio_output_init(uint32_t rate) { assert(rate==8000); return true; }
bool audio_output_write(const int16_t *pcm, size_t n) {
    assert(n==320);
    for (unsigned i=0; i<160; ++i) assert(pcm[2*i]==pcm[2*i+1]);
    ++writes;
    if (writes==8) voice_session_stop();
    return true;
}
int main(void) {
    uint8_t payload[55]={AUDIO_DATA_CODEC2, 1, AUDIO_DIR_CONTROL_TX, 0, 1, 8, 6};
    voice_session_init();
    assert(!voice_session_handle_codec2(payload, sizeof(payload)));
    assert(!voice_session_set_direction(AUDIO_DIR_CONTROL_TX)); // data/non-P4 SET cannot start call
    assert(!voice_session_sync_direction((audio_direction_t)99));
    assert(!voice_session_is_active());
    assert(voice_session_sync_direction(AUDIO_DIR_FIELD_TX));
    assert(!voice_session_handle_codec2(payload, sizeof(payload)));
    assert(voice_session_sync_direction(AUDIO_DIR_CONTROL_TX));
    assert(!voice_session_handle_codec2(payload, 54));
    assert(voice_session_handle_codec2(payload, 55));
    uint32_t old=s_generation;
    assert(voice_session_sync_direction(AUDIO_DIR_CONTROL_TX));
    assert(old==s_generation && count==1); // retries must not flush audio
    for (unsigned i=1; i<12; ++i) assert(voice_session_handle_codec2(payload, 55));
    assert(!voice_session_handle_codec2(payload, 55));
    if (setjmp(finished)==0) worker(NULL);
    assert(writes==8 && released==1 && !voice_session_is_active());
    assert(!voice_session_handle_codec2(payload, 55));
    writes=released=0;
    music_playing=true;
    voice_session_start();
    assert(voice_session_set_direction(AUDIO_DIR_CONTROL_TX));
    assert(voice_session_handle_codec2(payload, 55));
    if (setjmp(finished)==0) worker(NULL);
    assert(writes==8 && released==1 && music_paused && restored_rate==44100);
    puts("WROOM validation, queue bounds, real Codec2 decode, stereo PCM and stop: PASS");
    return 0;
}
'''

class VoicePlaybackTests(unittest.TestCase):
    @unittest.skipUnless(CODEC2_LIB, 'requires libcodec2')
    def test_worker(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name, text in HEADERS.items():
                p=root/name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(text)
            source=root/'harness.c'
            source.write_text(HARNESS)
            binary=root/'test'
            subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-I',str(root),'-I',str(MAIN),str(source),CODEC2_LIB if '/' in CODEC2_LIB else '-l:'+CODEC2_LIB,'-o',str(binary)],check=True)
            subprocess.run([str(binary)],check=True,timeout=5)
