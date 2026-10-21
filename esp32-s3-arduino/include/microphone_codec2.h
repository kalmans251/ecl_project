#pragma once

// Capture/encoding runs on a worker. BLE transmission stays in loop().
bool microphone_codec2_init();
void microphone_codec2_set_enabled(bool enabled);
void microphone_codec2_process();

// 0 pending, 1 ready (including physically stopped), 2 failed.
unsigned microphone_codec2_readiness();
