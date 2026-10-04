#pragma once

#include <Arduino.h>


typedef struct
{
    bool valid;

    int16_t x_mm;
    int16_t y_mm;

    int16_t speed_cms;

    uint16_t resolution_mm;

} radar_target_t;


void radar_manager_init(void);

void radar_manager_process(void);


void radar_manager_set_detail_enabled(
    bool enabled
);

bool radar_manager_is_detail_enabled(void);


bool radar_manager_set_position_source(
    uint8_t radar_id
);

uint8_t radar_manager_get_position_source(void);


uint8_t radar_manager_get_target_count(
    uint8_t radar_id
);