#pragma once

#include <stdbool.h>

#include "protocol.h"


bool p4_task_init(void);


bool p4_task_enqueue_tx(
    const protocol_frame_t *frame
);