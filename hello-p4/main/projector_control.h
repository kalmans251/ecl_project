#pragma once

#include <stdbool.h>


void projector_control_init(void);


void projector_control_set(
    bool enabled
);


bool projector_control_get(void);