#pragma once

#include <stdbool.h>
#include <stdint.h>


/* ============================================================
 * MUSIC PAUSE REASON
 *
 * 여러 이유가 동시에 존재할 수 있으므로 bitmask 사용.
 * ============================================================ */

typedef enum
{
    MUSIC_PAUSE_REASON_NONE =
        0,

    MUSIC_PAUSE_REASON_LED =
        (1 << 0),

    MUSIC_PAUSE_REASON_CALL =
        (1 << 1),

    MUSIC_PAUSE_REASON_USER =
        (1 << 2),

    MUSIC_PAUSE_REASON_EMERGENCY =
        (1 << 3),

} music_pause_reason_t;


/* ============================================================
 * INIT
 * ============================================================ */

void music_policy_init(void);


/* ============================================================
 * PAUSE REASON
 * ============================================================ */

void music_policy_add_pause_reason(
    music_pause_reason_t reason
);


void music_policy_remove_pause_reason(
    music_pause_reason_t reason
);


uint32_t music_policy_get_pause_reasons(void);


bool music_policy_is_blocked(void);


/* ============================================================
 * PLAYER STATE EVENT
 *
 * WROOM에서 오는 실제 player 상태를 알려준다.
 * ============================================================ */

void music_policy_on_started(void);

void music_policy_on_paused(void);

void music_policy_on_resumed(void);

void music_policy_on_finished(void);

void music_policy_on_error(void);

void music_policy_on_stopped(void);