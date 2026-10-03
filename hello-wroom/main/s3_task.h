#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "protocol.h"


bool s3_task_init(void);


bool s3_task_enqueue_tx(
    const protocol_frame_t *frame
);


void s3_task_on_ble_rx(
    const uint8_t *data,
    size_t len
);