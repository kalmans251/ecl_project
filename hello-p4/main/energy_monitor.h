#pragma once
#include <stdint.h>
/* Cached, independently valid readings. No I2C in the PLC controller task. */
#define ENERGY_WIRE_SIZE 15
void energy_monitor_init(void);
void energy_monitor_encode(uint8_t out[ENERGY_WIRE_SIZE]);
