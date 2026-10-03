#pragma once

#include <Arduino.h>

#include "protocol.h"


void ble_link_init(void);


/*
 * loop()에서 지속적으로 호출
 *
 * BLE callback이 StreamBuffer에 넣어놓은
 * 데이터를 여기에서 Parser로 처리한다.
 */
void ble_link_process(void);


bool ble_link_is_connected(void);


bool ble_send_frame(
    const protocol_frame_t *frame
);