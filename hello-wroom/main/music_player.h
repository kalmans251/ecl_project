#pragma once

#include <stdbool.h>


typedef enum
{
    MUSIC_PLAYER_IDLE = 0,

    MUSIC_PLAYER_PLAYING,

    MUSIC_PLAYER_PAUSED,

} music_player_state_t;


/* ============================================================
 * INIT
 * ============================================================ */

bool music_player_init(void);


/* ============================================================
 * CONTROL
 * ============================================================ */

bool music_player_start(
    const char *path
);


bool music_player_stop(void);


bool music_player_pause(void);


bool music_player_resume(void);


/* ============================================================
 * STATE
 * ============================================================ */

music_player_state_t
music_player_get_state(void);


bool music_player_is_playing(void);


bool music_player_is_paused(void);