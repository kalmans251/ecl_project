#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "protocol.h"


/* ============================================================
 * CALL ORIGIN
 * ============================================================ */

typedef enum
{
    /*
     * 관제에서 평상시 통화 버튼을 눌러 시작
     */
    CALL_ORIGIN_NORMAL = 0x00,


    /*
     * 비상벨 이후 통화
     *
     * Emergency Manager 구현 시 사용
     */
    CALL_ORIGIN_EMERGENCY = 0x01

} call_origin_t;


/* ============================================================
 * CALL STATE
 * ============================================================ */

typedef enum
{
    CALL_STATE_IDLE = 0x00,

    /*
     * 현장 -> 관제
     */
    CALL_STATE_FIELD_TX = 0x01,

    /*
     * 관제 -> 현장
     */
    CALL_STATE_CONTROL_TX = 0x02

} call_state_t;


/* ============================================================
 * INIT
 * ============================================================ */

void call_manager_init(void);


/* ============================================================
 * CALL CONTROL
 * ============================================================ */

bool call_manager_start(
    call_origin_t origin
);


bool call_manager_end(void);


/* ============================================================
 * DIRECTION / PTT
 * ============================================================ */

bool call_manager_set_direction(
    audio_direction_t direction
);


/* ============================================================
 * GET
 * ============================================================ */

bool call_manager_is_active(void);

call_state_t call_manager_get_state(void);

call_origin_t call_manager_get_origin(void);
/* Deprecated compatibility query: idle recovery grants are disabled. */
bool call_manager_end_recovery_active(void);

/* Controller task only; keepalives cannot start an idle call. */
void call_manager_keepalive(void);
void call_manager_tick(void);

/* Pi call session binding, accessed by the controller task only. */
bool call_manager_bind_session(uint32_t session);
bool call_manager_session_matches(uint32_t session);
bool call_manager_stop_session(uint32_t session);

bool call_manager_voice_allowed(const protocol_frame_t *frame);

bool call_manager_set_direction_ordered(uint32_t session, uint32_t request, audio_direction_t direction);

void call_manager_handle_readiness(const protocol_frame_t *frame);
