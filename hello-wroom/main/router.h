#pragma once

#include <stdbool.h>

#include "protocol.h"


bool router_init(void);


bool router_enqueue(
    const protocol_frame_t *frame
);