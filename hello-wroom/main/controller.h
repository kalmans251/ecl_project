#pragma once

#include <stdbool.h>

#include "protocol.h"


bool controller_init(void);


bool controller_enqueue(
    const protocol_frame_t *frame
);