#pragma once

#include "driver/uart.h"
#include "driver/spi_master.h"


/* ============================================================
 * NODE
 * ============================================================ */

#define RAILING_ID                  1


/* ============================================================
 * P4 UART
 * ============================================================ */

#define P4_UART_NUM                 UART_NUM_2

#define P4_UART_TX_PIN              22
#define P4_UART_RX_PIN              21

#define P4_UART_BAUD                115200

#define P4_UART_RX_BUF_SIZE         2048


/* ============================================================
 * SD CARD
 * ============================================================ */

#define SD_SPI_HOST                 SPI2_HOST

#define PIN_NUM_MISO                19
#define PIN_NUM_MOSI                23
#define PIN_NUM_CLK                 18
#define PIN_NUM_CS                  5

#define SD_MOUNT_POINT              "/sdcard"


/* ============================================================
 * I2S
 * ============================================================ */

#define I2S_BCLK_PIN                32
#define I2S_LRCK_PIN                33
#define I2S_DOUT_PIN                27


/* ============================================================
 * BLE
 * ============================================================ */

#define S3_BLE_DEVICE_NAME          "RAILING-S3-01"