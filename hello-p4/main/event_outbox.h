#pragma once
#include <stdbool.h>
#include "protocol.h"
/* Only unsolicited emergency START/STOP; local alarms are unaffected. */
bool event_outbox_capture(const protocol_frame_t *frame);
void event_outbox_reply(const protocol_frame_t *poll, protocol_frame_t *reply);
