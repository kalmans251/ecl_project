#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "protocol.h"


bool p4_uart_init(void);


int p4_uart_read(
    uint8_t *buffer,
    size_t buffer_size,
    uint32_t timeout_ms
);


bool p4_uart_send_frame(
    const protocol_frame_t *frame
);