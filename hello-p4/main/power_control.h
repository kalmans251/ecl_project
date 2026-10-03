#pragma once

#include <stdbool.h>


void power_control_init(void);


/* 상전 */
void power_control_set_ac(
    bool enabled
);


/* 배터리 */
void power_control_set_battery(
    bool enabled
);


/* 전원 전환 */
void power_control_select_ac(void);

void power_control_select_battery(void);


/* 현재 실제 GPIO 상태 */
bool power_control_get_ac(void);

bool power_control_get_battery(void);