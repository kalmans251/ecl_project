#pragma once
#include <stdbool.h>
#include "protocol.h"
#include "freertos/FreeRTOS.h"
/* Controller task scope: annotate only that task's matching WROOM command. */
void control_confirm_begin(const protocol_frame_t *request);
bool control_confirm_end(void);
bool control_confirm_send_music(protocol_frame_t *frame, TickType_t wait);
