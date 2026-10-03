#include "p4_uart.h"

#include "board_config.h"

#include "driver/uart.h"

#include "esp_err.h"
#include "esp_log.h"

#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"


static const char *TAG =
    "P4_UART";


static SemaphoreHandle_t
s_tx_mutex =
    NULL;


/* ============================================================
 * INIT
 * ============================================================ */

bool p4_uart_init(void)
{
    uart_config_t config =
    {
        .baud_rate =
            P4_UART_BAUD,

        .data_bits =
            UART_DATA_8_BITS,

        .parity =
            UART_PARITY_DISABLE,

        .stop_bits =
            UART_STOP_BITS_1,

        .flow_ctrl =
            UART_HW_FLOWCTRL_DISABLE,

        .source_clk =
            UART_SCLK_DEFAULT,
    };


    esp_err_t err =
        uart_driver_install(
            P4_UART_NUM,
            P4_UART_RX_BUF_SIZE,
            0,
            0,
            NULL,
            0
        );


    if (
        err != ESP_OK &&
        err != ESP_ERR_INVALID_STATE
    )
    {
        ESP_LOGE(
            TAG,
            "uart_driver_install failed: %s",
            esp_err_to_name(err)
        );

        return false;
    }


    ESP_ERROR_CHECK(
        uart_param_config(
            P4_UART_NUM,
            &config
        )
    );


    ESP_ERROR_CHECK(
        uart_set_pin(
            P4_UART_NUM,

            P4_UART_TX_PIN,
            P4_UART_RX_PIN,

            UART_PIN_NO_CHANGE,
            UART_PIN_NO_CHANGE
        )
    );


    if (
        s_tx_mutex ==
        NULL
    )
    {
        s_tx_mutex =
            xSemaphoreCreateMutex();


        if (
            s_tx_mutex ==
            NULL
        )
        {
            return false;
        }
    }


    ESP_LOGI(
        TAG,
        "UART ready TX=%d RX=%d BAUD=%d",
        P4_UART_TX_PIN,
        P4_UART_RX_PIN,
        P4_UART_BAUD
    );


    return true;
}


/* ============================================================
 * READ
 * ============================================================ */

int p4_uart_read(
    uint8_t *buffer,
    size_t buffer_size,
    uint32_t timeout_ms
)
{
    if (
        buffer == NULL ||
        buffer_size == 0
    )
    {
        return 0;
    }


    return uart_read_bytes(
        P4_UART_NUM,

        buffer,
        buffer_size,

        pdMS_TO_TICKS(
            timeout_ms
        )
    );
}


/* ============================================================
 * SEND FRAME
 * ============================================================ */

bool p4_uart_send_frame(
    const protocol_frame_t *frame
)
{
    uint8_t encoded[
        PROTOCOL_MAX_FRAME_SIZE
    ];


    size_t encoded_len =
        0;


    if (
        !protocol_encode(
            frame,

            encoded,
            sizeof(encoded),

            &encoded_len
        )
    )
    {
        return false;
    }


    if (
        xSemaphoreTake(
            s_tx_mutex,
            pdMS_TO_TICKS(100)
        )
        !=
        pdTRUE
    )
    {
        return false;
    }


    int written =
        uart_write_bytes(
            P4_UART_NUM,
            encoded,
            encoded_len
        );


    uart_wait_tx_done(
        P4_UART_NUM,
        pdMS_TO_TICKS(100)
    );


    xSemaphoreGive(
        s_tx_mutex
    );


    return
        written ==
        (int)encoded_len;
}