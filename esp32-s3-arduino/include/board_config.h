#pragma once
#include <Arduino.h>

// ============================================================
// RAILING
// ============================================================

#define RAILING_ID             0x01


// ============================================================
// BLE
// ============================================================

#define BLE_DEVICE_NAME        "RAILING-S3-01"


// Service
//
// 7a100001-8e7f-4b6c-9a2d-100000000001
//
#define BLE_SERVICE_UUID       \
    "7a100001-8e7f-4b6c-9a2d-100000000001"


// WROOM -> S3
//
// WRITE / WRITE_NR
//
// 7a100002-8e7f-4b6c-9a2d-100000000002
//
#define BLE_RX_CHAR_UUID       \
    "7a100002-8e7f-4b6c-9a2d-100000000002"


// S3 -> WROOM
//
// NOTIFY
//
// 7a100003-8e7f-4b6c-9a2d-100000000003
//
#define BLE_TX_CHAR_UUID       \
    "7a100003-8e7f-4b6c-9a2d-100000000003"


// ============================================================
// BLE BUFFER
// ============================================================

#define BLE_RX_STREAM_SIZE     2048
#define BLE_RX_PROCESS_SIZE    256


// ============================================================
// BLE MTU
// ============================================================

#define BLE_PREFERRED_MTU      185


// ============================================================
// INMP441 MICROPHONE
// ============================================================

static constexpr int PIN_I2S_WS  = 7;
static constexpr int PIN_I2S_SCK = 6;
static constexpr int PIN_I2S_SD  = 5;

// INMP441 L/R: GND = LEFT, 3.3 V = RIGHT.
static constexpr bool MIC_USE_RIGHT_CHANNEL = false;
static constexpr int MIC_GAIN = 4;


// ============================================================
// LD2450 RADAR
//
// RADAR1 / RADAR2 모두 사람 감지에 사용
// 위치 좌표는 선택된 Radar 하나만 관제로 전송
// ============================================================

static constexpr int RADAR1_RX_IO = 17;
static constexpr int RADAR1_TX_IO = 18;

static constexpr int RADAR2_RX_IO = 15;
static constexpr int RADAR2_TX_IO = 16;

static constexpr uint32_t LD2450_BAUDRATE =
    256000;


// 1 = RADAR1 좌표 사용
// 2 = RADAR2 좌표 사용
static constexpr uint8_t RADAR_POSITION_SOURCE =
    1;


// ============================================================
// EMERGENCY / VOICE CALL BUTTON
//
// 외부 10kΩ Pull-down
// Active HIGH
//
// HIGH가 3초 연속 유지되면 비상 활성화.
// ============================================================

static constexpr int PIN_VOICE_CALL_BUTTON =
    4;

static constexpr uint32_t EMERGENCY_HOLD_MS =
    3000;

static constexpr uint32_t EMERGENCY_DEBOUNCE_MS =
    50;
