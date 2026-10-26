#pragma once

#include <Arduino.h>


void emergency_button_init(void);

void emergency_button_process(void);


bool emergency_button_is_active(void);


/* P4 emergency state response, correlated by the original button sequence. */
void emergency_button_confirm(uint8_t state, uint32_t seq);
