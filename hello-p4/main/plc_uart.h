#pragma once

#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>


void plc_uart_init(void);

bool plc_uart_wait_tx_done(uint32_t timeout_ms);


int plc_uart_send(
    const uint8_t *data,
    size_t len
);


int plc_uart_receive(
    uint8_t *buffer,
    size_t max_len
);
