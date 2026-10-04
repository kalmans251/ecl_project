#include <Arduino.h>
#include <codec2.h>
#include <driver/i2s.h>
#include <freertos/queue.h>

#include "audio_session.h"
#include "ble_link.h"
#include "board_config.h"
#include "microphone_codec2.h"

namespace {
constexpr i2s_port_t kPort = I2S_NUM_0;
constexpr size_t kSamples = 160; // 20 ms at 8 kHz
constexpr size_t kBytesPerFrame = 6;
constexpr uint8_t kFramesPerPacket = 8;
constexpr uint32_t kMaxAgeMs = 320;
static_assert(kBytesPerFrame == CODEC2_2400_BYTES_PER_FRAME, "Codec2 frame size");
static_assert(kFramesPerPacket == CODEC2_MAX_FRAMES_PER_PACKET, "Codec2 packet size");
static_assert(MIC_GAIN > 0, "Microphone gain must be positive");

struct Packet {
    uint32_t generation;
    TickType_t captured;
    uint16_t sequence;
    uint8_t data[kBytesPerFrame * kFramesPerPacket];
};

QueueHandle_t s_packets = nullptr;
portMUX_TYPE s_lock = portMUX_INITIALIZER_UNLOCKED;
bool s_enabled = false;
uint32_t s_generation = 0;
uint32_t s_queue_drops = 0;
uint32_t s_peak = 0;
uint32_t s_clipped = 0;
uint32_t s_encode_us = 0;
uint32_t s_sent = 0;
uint32_t s_send_drops = 0;

void state(bool &enabled, uint32_t &generation) {
    portENTER_CRITICAL(&s_lock);
    enabled = s_enabled;
    generation = s_generation;
    portEXIT_CRITICAL(&s_lock);
}

bool init_i2s() {
    i2s_config_t config = {};
    config.mode = static_cast<i2s_mode_t>(I2S_MODE_MASTER | I2S_MODE_RX);
    config.sample_rate = 8000;
    config.bits_per_sample = I2S_BITS_PER_SAMPLE_32BIT;
    config.channel_format = MIC_USE_RIGHT_CHANNEL
        ? I2S_CHANNEL_FMT_ONLY_RIGHT : I2S_CHANNEL_FMT_ONLY_LEFT;
    config.communication_format = I2S_COMM_FORMAT_STAND_I2S;
    config.intr_alloc_flags = 0;
    config.dma_buf_count = 4;
    config.dma_buf_len = kSamples;
    config.use_apll = false;
    esp_err_t err = i2s_driver_install(kPort, &config, 0, nullptr);
    if (err != ESP_OK) {
        Serial.printf("[MIC] I2S install failed: %s\n", esp_err_to_name(err));
        return false;
    }
    i2s_pin_config_t pins = {};
    pins.mck_io_num = I2S_PIN_NO_CHANGE;
    pins.bck_io_num = PIN_I2S_SCK;
    pins.ws_io_num = PIN_I2S_WS;
    pins.data_out_num = I2S_PIN_NO_CHANGE;
    pins.data_in_num = PIN_I2S_SD;
    err = i2s_set_pin(kPort, &pins);
    if (err == ESP_OK) err = i2s_stop(kPort);
    if (err != ESP_OK) {
        Serial.printf("[MIC] I2S setup failed: %s\n", esp_err_to_name(err));
        i2s_driver_uninstall(kPort);
        return false;
    }
    return true;
}

void capture_task(void *) {
    // Keep the larger raw/PCM buffers off the task's stack.
    static int32_t raw[kSamples];
    static short pcm[kSamples];
    CODEC2 *codec = nullptr;
    Packet packet = {};
    size_t sample_count = 0;
    uint8_t frame_count = 0;
    uint16_t sequence = 0;
    uint32_t generation = 0;
    bool running = false;

    for (;;) {
        bool enabled;
        uint32_t requested;
        state(enabled, requested);
        if (running && (!enabled || requested != generation)) {
            i2s_stop(kPort);
            codec2_destroy(codec);
            codec = nullptr;
            running = false;
            sample_count = 0;
            frame_count = 0;
        }
        if (!enabled) {
            vTaskDelay(pdMS_TO_TICKS(5));
            continue;
        }
        if (!running) {
            generation = requested;
            codec = codec2_create(CODEC2_MODE_2400);
            if (codec == nullptr || codec2_samples_per_frame(codec) != kSamples
                || codec2_bits_per_frame(codec) != 48) {
                if (codec != nullptr) codec2_destroy(codec);
                codec = nullptr;
                Serial.println("[MIC] Codec2 2400 init failed; capture disabled");
                microphone_codec2_set_enabled(false);
                continue;
            }
            if (i2s_start(kPort) != ESP_OK) {
                codec2_destroy(codec);
                codec = nullptr;
                Serial.println("[MIC] I2S start failed; capture disabled");
                microphone_codec2_set_enabled(false);
                continue;
            }
            sequence = 0;
            running = true;
            // Discard queued DMA samples from an earlier direction/session.
            size_t discarded;
            while (i2s_read(kPort, raw, sizeof(raw), &discarded, 0) == ESP_OK
                   && discarded != 0) {}
            Serial.println("[MIC] FIELD_TX capture started: 8000 Hz / 160 samples / 6 bytes");
        }

        size_t bytes_read = 0;
        esp_err_t err = i2s_read(kPort, raw,
            (kSamples - sample_count) * sizeof(int32_t),
            &bytes_read, pdMS_TO_TICKS(25));
        bool still_enabled;
        uint32_t current;
        state(still_enabled, current);
        if (!still_enabled || current != generation) continue;
        if (err != ESP_OK && err != ESP_ERR_TIMEOUT) {
            Serial.printf("[MIC] I2S read failed: %s\n", esp_err_to_name(err));
            microphone_codec2_set_enabled(false);
            continue;
        }

        uint32_t peak = 0;
        uint32_t clipped = 0;
        for (size_t i = 0; i < bytes_read / sizeof(int32_t); ++i) {
            // INMP441: signed 24-bit data in the high bits of a 32-bit slot.
            int64_t value = static_cast<int64_t>(raw[i] / 65536) * MIC_GAIN;
            if (value > 32767) { value = 32767; ++clipped; }
            if (value < -32768) { value = -32768; ++clipped; }
            pcm[sample_count++] = static_cast<short>(value);
            uint32_t magnitude = value < 0 ? -value : value;
            if (magnitude > peak) peak = magnitude;
        }
        portENTER_CRITICAL(&s_lock);
        if (peak > s_peak) s_peak = peak;
        s_clipped += clipped;
        portEXIT_CRITICAL(&s_lock);
        if (sample_count != kSamples) continue;

        uint32_t started = micros();
        codec2_encode(codec, packet.data + frame_count * kBytesPerFrame, pcm);
        uint32_t elapsed = micros() - started;
        portENTER_CRITICAL(&s_lock);
        if (elapsed > s_encode_us) s_encode_us = elapsed;
        portEXIT_CRITICAL(&s_lock);
        sample_count = 0;
        if (++frame_count != kFramesPerPacket) continue;
        packet.generation = generation;
        packet.captured = xTaskGetTickCount();
        packet.sequence = sequence++;
        // Bound latency: never wait for BLE when capturing.
        if (xQueueSend(s_packets, &packet, 0) != pdTRUE) {
            portENTER_CRITICAL(&s_lock);
            ++s_queue_drops;
            portEXIT_CRITICAL(&s_lock);
        }
        frame_count = 0;
    }
}
} // namespace

bool microphone_codec2_init() {
    s_packets = xQueueCreate(2, sizeof(Packet));
    if (s_packets == nullptr) return false;
    if (!init_i2s()) {
        vQueueDelete(s_packets);
        s_packets = nullptr;
        return false;
    }
    if (xTaskCreate(capture_task, "mic-codec2", 16384, nullptr, 2, nullptr) != pdPASS) {
        i2s_driver_uninstall(kPort);
        vQueueDelete(s_packets);
        s_packets = nullptr;
        return false;
    }
    Serial.printf("[MIC] Ready WS=%d SCK=%d SD=%d channel=%s gain=%d\n",
        PIN_I2S_WS, PIN_I2S_SCK, PIN_I2S_SD,
        MIC_USE_RIGHT_CHANNEL ? "RIGHT" : "LEFT", MIC_GAIN);
    return true;
}

void microphone_codec2_set_enabled(bool enabled) {
    portENTER_CRITICAL(&s_lock);
    s_enabled = enabled;
    ++s_generation; // invalidate partial and queued audio, even across rapid PTT
    portEXIT_CRITICAL(&s_lock);
}

void microphone_codec2_process() {
    if (s_packets == nullptr) return;
    Packet packet;
    if (xQueueReceive(s_packets, &packet, 0) == pdTRUE) {
        bool enabled;
        uint32_t generation;
        state(enabled, generation);
        if (enabled && packet.generation == generation
            && xTaskGetTickCount() - packet.captured <= pdMS_TO_TICKS(kMaxAgeMs)
            && audio_session_field_tx_enabled() && ble_link_is_connected()) {
            if (audio_session_send_codec2(packet.data, kFramesPerPacket, packet.sequence))
                ++s_sent;
            else ++s_send_drops;
        } else ++s_send_drops;
    }
    static uint32_t last_report = 0;
    uint32_t now = millis();
    if (audio_session_field_tx_enabled() && now - last_report >= 5000) {
        last_report = now;
        portENTER_CRITICAL(&s_lock);
        uint32_t peak = s_peak, clipped = s_clipped;
        uint32_t drops = s_queue_drops, encode_us = s_encode_us;
        s_peak = 0; s_clipped = 0; s_encode_us = 0;
        portEXIT_CRITICAL(&s_lock);
        Serial.printf("[MIC] sent=%lu drop=%lu queue_drop=%lu peak=%lu clip=%lu encode_max_us=%lu\n",
            (unsigned long)s_sent, (unsigned long)s_send_drops, (unsigned long)drops,
            (unsigned long)peak, (unsigned long)clipped, (unsigned long)encode_us);
    }
}
