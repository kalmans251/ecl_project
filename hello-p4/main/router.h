#pragma once

#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"

#include "protocol.h"


extern QueueHandle_t router_queue;

extern QueueHandle_t plc_tx_queue;

extern QueueHandle_t wroom_tx_queue;

extern QueueHandle_t p4_controller_queue;


void router_init(void);

void router_task(void *arg);