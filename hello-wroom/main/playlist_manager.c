#include "playlist_manager.h"

#include <dirent.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <strings.h>

#include "esp_log.h"
#include "esp_system.h"
#include "esp_random.h"

#include "music_player.h"
#include "sd_card.h"


static const char *TAG =
    "PLAYLIST";



/* ============================================================
 * CONFIG
 * ============================================================ */

#define PLAYLIST_MAX_TRACKS_PER_GROUP   32

#define PLAYLIST_FILENAME_MAX           96

#define PLAYLIST_PATH_MAX               256


/* ============================================================
 * TRACK
 * ============================================================ */

typedef struct
{
    char filename[
        PLAYLIST_FILENAME_MAX
    ];

} playlist_track_t;


/* ============================================================
 * GROUP CATALOG
 * ============================================================ */

typedef struct
{
    music_group_t group;

    const char *directory;

    playlist_track_t tracks[
        PLAYLIST_MAX_TRACKS_PER_GROUP
    ];

    uint16_t count;

    /*
     * 그룹마다 현재 위치를 따로 기억.
     *
     * AGE 모드에서
     * 20대 → 30대 → 다시 20대가 되어도
     * 20대 그룹의 이전 진행 위치를 기억할 수 있음.
     */
    int16_t current_index;

} playlist_group_catalog_t;


/* ============================================================
 * GROUPS
 * ============================================================ */

static playlist_group_catalog_t
s_groups[] =
{
    {
        .group =
            MUSIC_GROUP_DEFAULT,

        .directory =
            "/sdcard/music/default",

        .count =
            0,

        .current_index =
            -1,
    },

    {
        .group =
            MUSIC_GROUP_10S,

        .directory =
            "/sdcard/music/10",

        .count =
            0,

        .current_index =
            -1,
    },

    {
        .group =
            MUSIC_GROUP_20S,

        .directory =
            "/sdcard/music/20",

        .count =
            0,

        .current_index =
            -1,
    },

    {
        .group =
            MUSIC_GROUP_30S,

        .directory =
            "/sdcard/music/30",

        .count =
            0,

        .current_index =
            -1,
    },

    {
        .group =
            MUSIC_GROUP_40S,

        .directory =
            "/sdcard/music/40",

        .count =
            0,

        .current_index =
            -1,
    },
};


#define PLAYLIST_GROUP_COUNT \
    (sizeof(s_groups) / sizeof(s_groups[0]))


/* ============================================================
 * STATE
 * ============================================================ */

static bool
s_initialized =
    false;


static music_play_mode_t
s_mode =
    MUSIC_PLAY_MODE_SEQUENTIAL;


static music_group_t
s_age_group =
    MUSIC_GROUP_DEFAULT;

static uint32_t
s_catalog_version =
    0;

/* ============================================================
 * CATALOG HASH
 * ============================================================ */

static uint32_t hash_byte(
    uint32_t hash,
    uint8_t value
)
{
    hash ^= value;
    hash *= 16777619u;

    return hash;
}


static uint32_t calculate_catalog_version(void)
{
    uint32_t hash =
        2166136261u;


    for (
        size_t g = 0;
        g < PLAYLIST_GROUP_COUNT;
        g++
    )
    {
        playlist_group_catalog_t *catalog =
            &s_groups[g];


        /*
         * 그룹 구분.
         */
        hash =
            hash_byte(
                hash,
                (uint8_t)catalog->group
            );


        /*
         * 곡 개수도 포함.
         */
        hash =
            hash_byte(
                hash,
                (uint8_t)(
                    catalog->count
                    >> 8
                )
            );

        hash =
            hash_byte(
                hash,
                (uint8_t)(
                    catalog->count
                    &
                    0xFF
                )
            );


        /*
         * scan_group() 이후 filename이 정렬되어 있으므로
         * SD directory enumeration 순서와 무관하게
         * 동일한 목록이면 동일한 version이 나온다.
         */
        for (
            uint16_t i = 0;
            i < catalog->count;
            i++
        )
        {
            const char *name =
                catalog->tracks[i].filename;


            while (
                *name != '\0'
            )
            {
                hash =
                    hash_byte(
                        hash,
                        (uint8_t)*name
                    );

                name++;
            }


            /*
             * 파일명 경계.
             */
            hash =
                hash_byte(
                    hash,
                    0
                );
        }
    }


    return hash;
}

/* ============================================================
 * MP3 EXTENSION
 * ============================================================ */

static bool is_mp3_filename(
    const char *name
)
{
    if (
        name ==
        NULL
    )
    {
        return false;
    }


    size_t length =
        strlen(
            name
        );


    if (
        length <
        4
    )
    {
        return false;
    }


    const char *extension =
        &name[
            length -
            4
        ];


    return
        strcasecmp(
            extension,
            ".mp3"
        )
        ==
        0;
}


/* ============================================================
 * SORT
 *
 * 파일명을 정렬해서 SD카드를 다시 넣어도
 * 순차 재생 순서를 최대한 일정하게 유지.
 * ============================================================ */

static int compare_track(
    const void *a,
    const void *b
)
{
    const playlist_track_t *track_a =
        (const playlist_track_t *)a;


    const playlist_track_t *track_b =
        (const playlist_track_t *)b;


    return
        strcasecmp(
            track_a->filename,
            track_b->filename
        );
}


/* ============================================================
 * FIND GROUP
 * ============================================================ */

static playlist_group_catalog_t *
find_group(
    music_group_t group
)
{
    for (
        size_t i = 0;
        i < PLAYLIST_GROUP_COUNT;
        i++
    )
    {
        if (
            s_groups[i].group ==
            group
        )
        {
            return
                &s_groups[i];
        }
    }


    return NULL;
}


/* ============================================================
 * SCAN GROUP
 * ============================================================ */

static bool scan_group(
    playlist_group_catalog_t *catalog
)
{
    if (
        catalog ==
        NULL
    )
    {
        return false;
    }


    catalog->count =
        0;


    catalog->current_index =
        -1;


    DIR *dir =
        opendir(
            catalog->directory
        );


    if (
        dir ==
        NULL
    )
    {
        ESP_LOGW(
            TAG,
            "Directory not found: %s",
            catalog->directory
        );


        return false;
    }


    struct dirent *entry;


    while (
        (
            entry =
                readdir(
                    dir
                )
        )
        !=
        NULL
    )
    {
        if (
            entry->d_name[0] ==
            '.'
        )
        {
            continue;
        }


        if (
            !is_mp3_filename(
                entry->d_name
            )
        )
        {
            continue;
        }


        if (
            catalog->count >=
            PLAYLIST_MAX_TRACKS_PER_GROUP
        )
        {
            ESP_LOGW(
                TAG,
                "%s track limit reached (%d)",
                catalog->directory,
                PLAYLIST_MAX_TRACKS_PER_GROUP
            );


            break;
        }


        size_t length =
            strlen(
                entry->d_name
            );


        if (
            length + 1 >
            PLAYLIST_FILENAME_MAX
        )
        {
            ESP_LOGW(
                TAG,
                "Filename too long: %s",
                entry->d_name
            );


            continue;
        }


        playlist_track_t *track =
            &catalog->tracks[
                catalog->count
            ];


        memcpy(
            track->filename,
            entry->d_name,
            length + 1
        );


        catalog->count++;
    }


    closedir(
        dir
    );


    if (
        catalog->count >
        1
    )
    {
        qsort(
            catalog->tracks,
            catalog->count,
            sizeof(
                playlist_track_t
            ),
            compare_track
        );
    }


    ESP_LOGI(
        TAG,
        "GROUP %d / %s / tracks=%u",
        catalog->group,
        catalog->directory,
        (unsigned)catalog->count
    );


    return true;
}


/* ============================================================
 * ACTIVE GROUP
 * ============================================================ */

static playlist_group_catalog_t *
get_active_group(void)
{
    /*
     * AGE 모드일 때만
     * 연령대 그룹 사용.
     */
    if (
        s_mode ==
        MUSIC_PLAY_MODE_AGE
    )
    {
        playlist_group_catalog_t *group =
            find_group(
                s_age_group
            );


        if (
            group != NULL &&
            group->count > 0
        )
        {
            return group;
        }


        /*
         * 연령대 폴더가 비어 있거나
         * 아직 연령대가 정해지지 않았으면 default.
         */
        return
            find_group(
                MUSIC_GROUP_DEFAULT
            );
    }


    /*
     * SEQUENTIAL / SHUFFLE은
     * 일반 음악인 default 폴더 사용.
     */
    return
        find_group(
            MUSIC_GROUP_DEFAULT
        );
}


/* ============================================================
 * BUILD PATH
 * ============================================================ */

static bool build_track_path(
    playlist_group_catalog_t *catalog,
    int16_t index,
    char *path,
    size_t path_size
)
{
    if (
        catalog == NULL ||
        path == NULL ||
        path_size == 0
    )
    {
        return false;
    }


    if (
        index < 0 ||
        index >=
            (int16_t)catalog->count
    )
    {
        return false;
    }


    int result =
        snprintf(
            path,
            path_size,
            "%s/%s",
            catalog->directory,
            catalog->tracks[
                index
            ].filename
        );


    if (
        result < 0 ||
        result >=
            (int)path_size
    )
    {
        return false;
    }


    return true;
}


/* ============================================================
 * PLAY INDEX
 * ============================================================ */

static bool play_index(
    playlist_group_catalog_t *catalog,
    int16_t index
)
{
    if (
        catalog ==
        NULL
    )
    {
        return false;
    }


    char path[
        PLAYLIST_PATH_MAX
    ];


    if (
        !build_track_path(
            catalog,
            index,
            path,
            sizeof(path)
        )
    )
    {
        return false;
    }


    ESP_LOGI(
        TAG,
        "PLAY group=%d index=%d/%u file=%s",
        catalog->group,
        index,
        (unsigned)catalog->count,
        path
    );


    /*
     * music_player_start()는
     * 이미 다른 곡이 재생 중이어도
     * 내부적으로 RESTART 처리 가능.
     */
    if (
        !music_player_start(
            path
        )
    )
    {
        ESP_LOGE(
            TAG,
            "music_player_start failed"
        );


        return false;
    }


    catalog->current_index =
        index;


    return true;
}


/* ============================================================
 * SHUFFLE INDEX
 * ============================================================ */

static int16_t choose_shuffle_index(
    playlist_group_catalog_t *catalog
)
{
    if (
        catalog ==
        NULL ||
        catalog->count ==
        0
    )
    {
        return -1;
    }


    if (
        catalog->count ==
        1
    )
    {
        return 0;
    }


    int16_t current =
        catalog->current_index;


    int16_t next;


    do
    {
        next =
            (int16_t)(
                esp_random()
                %
                catalog->count
            );

    }
    while (
        next ==
        current
    );


    return next;
}

/* ============================================================
 * RESCAN
 * ============================================================ */

bool playlist_manager_rescan(void)
{
    if (
        !sd_card_is_mounted()
    )
    {
        ESP_LOGW(
            TAG,
            "RESCAN failed: SD card not mounted"
        );

        return false;
    }


    ESP_LOGI(
        TAG,
        "Playlist RESCAN start"
    );


    /*
     * 각 그룹을 새로 스캔한다.
     *
     * scan_group() 내부에서:
     * - count = 0
     * - current_index = -1
     * 로 초기화된다.
     */
    for (
        size_t i = 0;
        i < PLAYLIST_GROUP_COUNT;
        i++
    )
    {
        scan_group(
            &s_groups[i]
        );
    }

    s_catalog_version =
        calculate_catalog_version();


    ESP_LOGI(
        TAG,
        "Catalog version = 0x%08lX",
        (unsigned long)s_catalog_version
    );

    /*
     * 재스캔에서는
     * s_mode / s_age_group은 건드리지 않는다.
     *
     * 예:
     * AGE + 20대 상태에서 SD 교체
     * → 다시 20대 그룹을 계속 사용 가능.
     */
    s_initialized =
        true;


    ESP_LOGI(
        TAG,
        "Playlist RESCAN complete"
    );


    return true;
}

/* ============================================================
 * INIT
 * ============================================================ */

bool playlist_manager_init(void)
{
    if (
        s_initialized
    )
    {
        return true;
    }


    if (
        !sd_card_is_mounted()
    )
    {
        ESP_LOGE(
            TAG,
            "SD card not mounted"
        );

        return false;
    }


    /*
     * 부팅 기본값.
     *
     * RESCAN에서는 이 값들을 유지하기 때문에
     * 여기서만 초기화한다.
     */
    s_mode =
        MUSIC_PLAY_MODE_SEQUENTIAL;


    s_age_group =
        MUSIC_GROUP_DEFAULT;


    if (
        !playlist_manager_rescan()
    )
    {
        return false;
    }


    ESP_LOGI(
        TAG,
        "Playlist manager ready"
    );


    return true;
}


/* ============================================================
 * SET MODE
 * ============================================================ */

bool playlist_manager_set_mode(
    music_play_mode_t mode
)
{
    if (
        mode !=
            MUSIC_PLAY_MODE_SEQUENTIAL
        &&
        mode !=
            MUSIC_PLAY_MODE_SHUFFLE
        &&
        mode !=
            MUSIC_PLAY_MODE_AGE
    )
    {
        return false;
    }


    s_mode =
        mode;


    ESP_LOGI(
        TAG,
        "PLAY MODE -> %d",
        mode
    );


    return true;
}


music_play_mode_t
playlist_manager_get_mode(void)
{
    return s_mode;
}


/* ============================================================
 * SET GROUP
 * ============================================================ */

bool playlist_manager_set_group(
    music_group_t group
)
{
    if (
        group !=
            MUSIC_GROUP_DEFAULT
        &&
        group !=
            MUSIC_GROUP_10S
        &&
        group !=
            MUSIC_GROUP_20S
        &&
        group !=
            MUSIC_GROUP_30S
        &&
        group !=
            MUSIC_GROUP_40S
    )
    {
        return false;
    }


    s_age_group =
        group;


    ESP_LOGI(
        TAG,
        "AGE GROUP -> %d",
        group
    );


    return true;
}


music_group_t
playlist_manager_get_group(void)
{
    return s_age_group;
}


/* ============================================================
 * START
 * ============================================================ */

bool playlist_manager_start(void)
{
    if (
        !s_initialized
    )
    {
        return false;
    }


    playlist_group_catalog_t *catalog =
        get_active_group();


    if (
        catalog == NULL ||
        catalog->count == 0
    )
    {
        ESP_LOGW(
            TAG,
            "No tracks"
        );

        return false;
    }


    int16_t index;


    /*
     * SHUFFLE / AGE:
     * 새 START마다 새 랜덤곡 선택.
     *
     * 직전 곡과 같은 곡은
     * choose_shuffle_index()가 제외한다.
     */
    if (
        s_mode == MUSIC_PLAY_MODE_SHUFFLE
        ||
        s_mode == MUSIC_PLAY_MODE_AGE
    )
    {
        index =
            choose_shuffle_index(
                catalog
            );
    }
    else
    {
        /*
         * SEQUENTIAL:
         * 기존 위치가 있으면 유지,
         * 없으면 첫 곡.
         */
        index =
            catalog->current_index;

        if (
            index < 0
        )
        {
            index =
                0;
        }
    }


    return
        play_index(
            catalog,
            index
        );
}


/* ============================================================
 * NEXT
 * ============================================================ */

bool playlist_manager_next(void)
{
    if (
        !s_initialized
    )
    {
        return false;
    }


    playlist_group_catalog_t *catalog =
        get_active_group();


    if (
        catalog == NULL ||
        catalog->count ==
        0
    )
    {
        ESP_LOGW(
            TAG,
            "No tracks for NEXT"
        );


        return false;
    }


    int16_t next_index;


    if (
        s_mode ==
            MUSIC_PLAY_MODE_SHUFFLE
        ||
        s_mode ==
            MUSIC_PLAY_MODE_AGE
    )
    {
        next_index =
            choose_shuffle_index(
                catalog
            );
    }
    else
    {
        if (
            catalog->current_index <
            0
        )
        {
            next_index =
                0;
        }
        else
        {
            next_index =
                catalog->current_index
                +
                1;


            if (
                next_index >=
                (int16_t)catalog->count
            )
            {
                next_index =
                    0;
            }
        }
    }


    return
        play_index(
            catalog,
            next_index
        );
}


/* ============================================================
 * INFO
 * ============================================================ */

uint16_t
playlist_manager_get_track_count(void)
{
    playlist_group_catalog_t *catalog =
        get_active_group();


    if (
        catalog ==
        NULL
    )
    {
        return 0;
    }


    return
        catalog->count;
}


int16_t
playlist_manager_get_current_index(void)
{
    playlist_group_catalog_t *catalog =
        get_active_group();


    if (
        catalog ==
        NULL
    )
    {
        return -1;
    }


    return
        catalog->current_index;
}

/* ============================================================
 * CATALOG VERSION
 * ============================================================ */

uint32_t
playlist_manager_get_catalog_version(void)
{
    return s_catalog_version;
}


/* ============================================================
 * TOTAL TRACK COUNT
 * ============================================================ */

uint16_t
playlist_manager_get_total_track_count(void)
{
    uint16_t total =
        0;


    for (
        size_t i = 0;
        i < PLAYLIST_GROUP_COUNT;
        i++
    )
    {
        total +=
            s_groups[i].count;
    }


    return total;
}


/* ============================================================
 * GROUP TRACK COUNT
 * ============================================================ */

uint16_t
playlist_manager_get_group_track_count(
    music_group_t group
)
{
    playlist_group_catalog_t *catalog =
        find_group(
            group
        );


    if (
        catalog == NULL
    )
    {
        return 0;
    }


    return
        catalog->count;
}