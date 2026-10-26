#pragma once
#include "system_state.h"
#include <stdint.h>
/* Versioned status detail, requested explicitly via SYSTEM/APPLY STATUS [1].
 * This is controller-observed state; electrical measurements are not invented. */
#define STATUS_SNAPSHOT_SIZE 16
static inline void status_snapshot_encode(uint8_t *p,const p4_system_state_t *s,
        bool power_on,bool projector_on,uint8_t source,uint8_t music_mode,
        uint32_t count,bool emergency) {
    p[0]=1;p[1]=(uint8_t)s->power_mode;p[2]=power_on;
    p[3]=s->led_enabled;p[4]=(uint8_t)s->led_mode;p[5]=(uint8_t)s->weather_type;
    p[6]=projector_on;p[7]=s->sleep_mode_enabled;p[8]=s->sleep_active;
    p[9]=source;p[10]=music_mode;
    p[11]=count>>24;p[12]=count>>16;p[13]=count>>8;p[14]=count;p[15]=emergency;
}
