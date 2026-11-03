#pragma once
#include <stdbool.h>
#include "protocol.h"
/* Called only by router_task: no cross-task cache access. */
bool radar_cache_capture(const protocol_frame_t *frame);
bool radar_cache_reply(const protocol_frame_t *request, protocol_frame_t *reply);

/* Atomic receive gate; called by controller task. */
void radar_cache_set_enabled(bool enabled);
