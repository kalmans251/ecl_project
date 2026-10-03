#include "plc_uart.h"

#include "board_config.h"

#include "driver/uart.h"

#include "freertos/FreeRTOS.h"


void plc_uart_init(void)
{
    uart_config_t config = {

        .baud_rate =
            PLC_BAUD_RATE,

        .data_bits =
            UART_DATA_8_BITS,

        .parity =
            UART_PARITY_DISABLE,

        .stop_bits =
            UART_STOP_BITS_1,

        .flow_ctrl =
            UART_HW_FLOWCTRL_DISABLE,

        .source_clk =
            UART_SCLK_DEFAULT
    };


    uart_driver_install(
        PLC_UART_NUM,
        PLC_RX_BUF_SIZE,
        PLC_RX_BUF_SIZE,
        0,
        NULL,
        0
    );


    uart_param_config(
        PLC_UART_NUM,
        &config
    );


    uart_set_pin(
        PLC_UART_NUM,

        PLC_TX_PIN,
        PLC_RX_PIN,

        UART_PIN_NO_CHANGE,
        UART_PIN_NO_CHANGE
    );
}


int plc_uart_send(
    const uint8_t *data,
    size_t len
)
{
    return uart_write_bytes(
        PLC_UART_NUM,
        data,
        len
    );
}


int plc_uart_receive(
    uint8_t *buffer,
    size_t max_len
)
{
    return uart_read_bytes(
        PLC_UART_NUM,
        buffer,
        max_len,

        pdMS_TO_TICKS(10)
    );
}