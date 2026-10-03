#pragma once

#include <stdbool.h>

#include "protocol.h"
#include "detection_manager.h"
#include "system_state.h"


/* ============================================================
 * INIT
 * ============================================================ */

void music_manager_init(void);


/* ============================================================
 * MODE
 * ============================================================ */

bool music_manager_set_mode(
    music_play_mode_t mode
);

music_play_mode_t
music_manager_get_mode(void);


/* ============================================================
 * SESSION
 * ============================================================ */

bool music_manager_start(void);

bool music_manager_stop(void);

bool music_manager_next(void);

bool music_manager_is_session_enabled(void);


/* ============================================================
 * USER PAUSE
 * ============================================================ */

void music_manager_user_pause(void);

void music_manager_user_resume(void);


/* ============================================================
 * SYSTEM EVENTS
 * ============================================================ */

void music_manager_on_detection_source_changed(
    detection_source_t source
);


/*
 * CCTV AGE 결과.
 *
 * AGE 모드가 아니면 아무것도 하지 않음.
 */
void music_manager_on_age_result(
    age_group_t age
);


/*
 * 현재 재생곡이 자연 종료됨.
 *
 * entered_sleep:
 * true  = 이 FINISHED 때문에 Sleep에 들어감
 * false = 계속 Active
 */
void music_manager_on_track_finished(
    bool entered_sleep
);


/*
 * 실제 Sleep 상태에서 Active로 복귀했을 때 호출.
 */
void music_manager_on_wake(
    age_group_t age
);


/*
 * LED 모드 변경.
 *
 * music_policy가 PAUSE/RESUME을 처리한 뒤 호출.
 */
void music_manager_on_led_mode_changed(
    led_mode_t mode
);


/*
 * CCTV wake 시 AGE_RESULT를 기다려야 하는지.
 */
bool music_manager_requires_age_for_wake(void);