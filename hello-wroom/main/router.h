#pragma once

#include <stdbool.h>

#include "protocol.h"


bool router_init(void);


bool router_enqueue(
    const protocol_frame_t *frame
);
/* Best-effort display telemetry; never wait for queue space. */
bool router_try_enqueue(const protocol_frame_t *frame);
