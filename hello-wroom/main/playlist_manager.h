#pragma once

#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>

#include "protocol.h"


/* ============================================================
 * INIT
 * ============================================================ */

bool playlist_manager_init(void);


/* ============================================================
 * MODE
 * ============================================================ */

bool playlist_manager_set_mode(
    music_play_mode_t mode
);

music_play_mode_t
playlist_manager_get_mode(void);


/* ============================================================
 * GROUP
 * ============================================================ */

bool playlist_manager_set_group(
    music_group_t group
);

music_group_t
playlist_manager_get_group(void);


/* ============================================================
 * PLAY CONTROL
 * ============================================================ */

/*
 * 현재 선택된 곡 재생.
 *
 * 아직 선택된 곡이 없으면
 * 현재 모드에 맞는 첫 곡을 선택.
 */
bool playlist_manager_start(void);


/*
 * 현재 모드에 맞는 다음 곡 선택 후 재생.
 */
bool playlist_manager_next(void);


/* ============================================================
 * INFO
 * ============================================================ */

uint16_t playlist_manager_get_track_count(void);

int16_t playlist_manager_get_current_index(void);

/* ============================================================
 * RESCAN
 *
 * SD 카드의 음악 목록을 다시 읽는다.
 * 현재 play mode / age group 설정은 유지한다.
 * ============================================================ */

bool playlist_manager_rescan(void);

/* ============================================================
 * CATALOG INFO
 * ============================================================ */

uint32_t playlist_manager_get_catalog_version(void);

uint16_t playlist_manager_get_total_track_count(void);

uint16_t playlist_manager_get_group_track_count(
    music_group_t group
);

bool playlist_manager_get_track_filename(
    music_group_t group,
    uint16_t index,
    char *out,
    size_t out_size
);