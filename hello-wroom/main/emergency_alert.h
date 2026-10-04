#pragma once

#include <stdbool.h>


bool emergency_alert_init(void);

bool emergency_alert_start(void);

bool emergency_alert_stop(void);

bool emergency_alert_is_active(void);
