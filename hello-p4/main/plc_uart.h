#pragma once

#include <stdint.h>
#include <stddef.h>


void plc_uart_init(void);


int plc_uart_send(
    const uint8_t *data,
    size_t len
);


int plc_uart_receive(
    uint8_t *buffer,
    size_t max_len
);