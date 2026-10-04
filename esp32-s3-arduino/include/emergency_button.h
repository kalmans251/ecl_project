#pragma once

#include <Arduino.h>


void emergency_button_init(void);

void emergency_button_process(void);


bool emergency_button_is_active(void);


/*
 * 관제 ACK 후 P4가 S3에게 알려줄 때 사용.
 */
void emergency_button_clear(void);