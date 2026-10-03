#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "detection_manager.h"
#include "system_state.h"

/* ============================================================
 * ACTIVITY STATE
 * ============================================================ */

typedef enum
{
    ACTIVITY_ACTIVE = 0,

    /*
     * 10초 무감지 상태지만
     * 현재 곡이 끝날 때까지 기다리는 중
     */
    ACTIVITY_SLEEP_PENDING,

    /*
     * 실제 슬립
     */
    ACTIVITY_SLEEPING,

    /*
     * CCTV 슬립 상태에서 사람이 새로 포착되어
     * 나이 결과를 기다리는 상태
     */
    ACTIVITY_WAIT_AGE

} activity_state_t;


/* ============================================================
 * INIT
 * ============================================================ */

void sleep_manager_init(void);


/* ============================================================
 * TASK
 * ============================================================ */

void sleep_manager_task(
    void *arg
);


/* ============================================================
 * SLEEP MODE ENABLE
 * ============================================================ */

void sleep_manager_set_enabled(
    bool enabled
);


/* ============================================================
 * DETECTION EVENT
 * ============================================================ */

void sleep_manager_on_new_detection(
    detection_source_t source,
    uint32_t seq,
    bool wait_for_age
);


void sleep_manager_on_cctv_age_result(
    uint32_t seq,
    age_group_t age
);


/* ============================================================
 * MUSIC EVENT
 * ============================================================ */

void sleep_manager_on_music_finished(void);


/* ============================================================
 * SOURCE CHANGE
 * ============================================================ */

void sleep_manager_reset_activity(void);


/* ============================================================
 * GET STATE
 * ============================================================ */

activity_state_t sleep_manager_get_state(void);

/* ============================================================
 * LED MODE CHANGE
 * ============================================================ */

void sleep_manager_on_led_mode_changed(
    led_mode_t mode
);