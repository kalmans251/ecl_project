#pragma once

#include "protocol.h"


void controller_init(void);


void controller_handle(
    const protocol_frame_t *frame
);