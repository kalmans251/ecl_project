#pragma once

#include "driver/uart.h"


/* ============================================================
 * 난간 ID
 * ============================================================ */

#define RAILING_ID              0x01


/* ============================================================
 * PLC UART
 *
 * Raspberry Pi
 *      ↕
 * PLCMODEM2
 *      ↕
 * ESP32-P4
 * ============================================================ */

#define PLC_UART_NUM            UART_NUM_1

#define PLC_TX_PIN              48
#define PLC_RX_PIN              47

#define PLC_BAUD_RATE           9600

// After granting Pi the bus, do not transmit any P4 frames for this interval.
#define PLC_CONTROL_WINDOW_MS   100
#define PLC_VOICE_PACKETS_PER_GRANT 2
#define PLC_IDLE_GRANT_MS       200

#define PLC_RX_BUF_SIZE         256


/* ============================================================
 * WROOM UART
 *
 * ESP32-P4
 *      ↕
 * ESP32-WROOM
 *
 * !!! 핀 번호는 실제 배선에 맞게 변경 !!!
 * ============================================================ */

#define WROOM_UART_NUM          UART_NUM_2

#define WROOM_TX_PIN            53
#define WROOM_RX_PIN            54

#define WROOM_BAUD_RATE         115200

#define WROOM_RX_BUF_SIZE       512

/* ============================================================
 * LED / WS2812
 * ============================================================ */

/* 우측 난간 */
#define LED_DATA_PIN_RIGHT      GPIO_NUM_4

/* 좌측 난간 */
#define LED_DATA_PIN_LEFT       GPIO_NUM_5


/* 4 x 31 serpentine */
#define LED_NUM_ROWS            4
#define LEDS_PER_ROW            31

#define LED_NUM_PER_SIDE        (LED_NUM_ROWS * LEDS_PER_ROW)

/* 양쪽 총 248개 */
#define LED_NUM_TOTAL           (LED_NUM_PER_SIDE * 2)

/* ============================================================
 * POWER CONTROL
 * ============================================================ */

/*
 * 상전 제어
 *
 * HIGH = 상전 ON
 * LOW  = 상전 OFF
 */
#define AC_POWER_GPIO      GPIO_NUM_2

/* 배터리
 * LOW  = CONNECT
 * HIGH = DISCONNECT
 *
 * Active Low
 */
#define BATTERY_POWER_GPIO     GPIO_NUM_6


/* ============================================================
 * PROJECTOR
 * ============================================================ */

/* HIGH = ON
 * LOW  = OFF
 */
#define PROJECTOR_GPIO         GPIO_NUM_11

/* ============================================================
 * INA219 / I2C
 * ============================================================ */

#define I2C_SDA_PIN          GPIO_NUM_8
#define I2C_SCL_PIN          GPIO_NUM_9

#define INA219_ADDR_LEFT     0x40
#define INA219_ADDR_RIGHT    0x41
