#pragma once
#include <stdbool.h>
#include "protocol.h"
/* Only unsolicited emergency START/STOP; local alarms are unaffected. */
bool event_outbox_capture(const protocol_frame_t *frame);
void event_outbox_reply(const protocol_frame_t *poll, protocol_frame_t *reply);

/* A reserved terminal-state mailbox cannot be displaced by emergency overflow. */
void event_outbox_store_call_end(const protocol_frame_t *frame);
void event_outbox_clear_call_end(void);
void event_outbox_store_call_fault(const protocol_frame_t *frame);
