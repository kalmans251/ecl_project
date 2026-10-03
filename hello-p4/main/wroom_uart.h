#pragma once

#include <stdint.h>
#include <stddef.h>


void wroom_uart_init(void);


int wroom_uart_send(
    const uint8_t *data,
    size_t len
);


int wroom_uart_receive(
    uint8_t *buffer,
    size_t max_len
);