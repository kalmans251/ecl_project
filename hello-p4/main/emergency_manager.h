#pragma once

#include <stdbool.h>
#include <stdint.h>


void emergency_manager_init(void);


bool emergency_manager_start(
    uint8_t source,
    uint32_t seq
);


bool emergency_manager_cancel(
    uint8_t source,
    uint32_t seq
);


bool emergency_manager_ack(
    uint32_t seq
);


bool emergency_manager_is_active(void);

uint32_t emergency_manager_get_seq(void);

uint8_t emergency_manager_get_source(void);