#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>


bool s3_ble_init(void);


bool s3_ble_is_ready(void);


bool s3_ble_send(
    const uint8_t *data,
    size_t len
);