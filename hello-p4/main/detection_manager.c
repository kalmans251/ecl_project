#include <string.h>
#include <limits.h>

#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"

#include "esp_log.h"
#include "esp_timer.h"

#include "detection_manager.h"


static const char *TAG =
    "DETECTION";


/* ============================================================
 * CONFIG
 * ============================================================ */

#define CCTV_EVENT_TABLE_SIZE       64

#define RADAR_RECENT_SEQ_SIZE       32


/* ============================================================
 * CCTV EVENT
 *
 * ENTER 이벤트와 나중에 도착하는 AGE_RESULT를 연결
 * ============================================================ */

typedef struct
{
    bool used;

    bool age_resolved;

    uint32_t seq;

    int64_t detected_ms;

} cctv_event_entry_t;


/* ============================================================
 * INTERNAL STATE
 * ============================================================ */

static SemaphoreHandle_t
    s_mutex =
        NULL;


static detection_summary_t
    s_summary;


static cctv_event_entry_t
    s_cctv_events[
        CCTV_EVENT_TABLE_SIZE
    ];


/*
 * Radar는 나이 결과 연결이 필요 없으므로
 * 최근 seq만 기억해서 재전송 중복을 방지.
 */

static uint32_t
    s_radar_recent_seq[
        RADAR_RECENT_SEQ_SIZE
    ];


static uint8_t
    s_radar_recent_count =
        0;


static uint8_t
    s_radar_recent_write =
        0;


/* ============================================================
 * TIME
 * ============================================================ */

static int64_t get_now_ms(void)
{
    return
        esp_timer_get_time()
        /
        1000;
}


/* ============================================================
 * LOCK
 * ============================================================ */

static void lock_manager(void)
{
    xSemaphoreTake(
        s_mutex,
        portMAX_DELAY
    );
}


static void unlock_manager(void)
{
    xSemaphoreGive(
        s_mutex
    );
}


/* ============================================================
 * AGE VALID
 * ============================================================ */

static bool age_is_valid(
    age_group_t age
)
{
    return
        age >= AGE_GROUP_10S &&
        age <= AGE_GROUP_40S;
}


/* ============================================================
 * GET AGE COUNT
 * ============================================================ */

static uint32_t get_age_count_locked(
    age_group_t age
)
{
    switch (age)
    {
        case AGE_GROUP_10S:
            return s_summary.age_10_count;

        case AGE_GROUP_20S:
            return s_summary.age_20_count;

        case AGE_GROUP_30S:
            return s_summary.age_30_count;

        case AGE_GROUP_40S:
            return s_summary.age_40_count;

        default:
            return 0;
    }
}


/* ============================================================
 * DOMINANT AGE
 *
 * 동률이면 가장 최근 연령대가 동률 그룹 중 하나인 경우
 * latest를 우선 선택.
 * ============================================================ */

static void update_dominant_age_locked(void)
{
    uint32_t max_count = 0;

    age_group_t dominant =
        AGE_GROUP_UNKNOWN;


    for (
        age_group_t age = AGE_GROUP_10S;
        age <= AGE_GROUP_40S;
        age++
    )
    {
        uint32_t count =
            get_age_count_locked(
                age
            );


        if (
            count >
            max_count
        )
        {
            max_count =
                count;

            dominant =
                age;
        }
    }


    if (
        max_count == 0
    )
    {
        s_summary.dominant_age_group =
            AGE_GROUP_UNKNOWN;

        return;
    }


    /*
     * 동률이면 latest를 우선
     */

    if (
        age_is_valid(
            s_summary.latest_age_group
        )
        &&
        get_age_count_locked(
            s_summary.latest_age_group
        )
        ==
        max_count
    )
    {
        dominant =
            s_summary.latest_age_group;
    }


    s_summary.dominant_age_group =
        dominant;
}


/* ============================================================
 * CCTV FIND EVENT
 * ============================================================ */

static int find_cctv_event_locked(
    uint32_t seq
)
{
    for (
        int i = 0;
        i < CCTV_EVENT_TABLE_SIZE;
        i++
    )
    {
        if (
            s_cctv_events[i].used &&
            s_cctv_events[i].seq == seq
        )
        {
            return i;
        }
    }


    return -1;
}


/* ============================================================
 * CCTV ALLOCATE SLOT
 * ============================================================ */

static int allocate_cctv_event_locked(void)
{
    /*
     * 먼저 빈 slot
     */

    for (
        int i = 0;
        i < CCTV_EVENT_TABLE_SIZE;
        i++
    )
    {
        if (
            !s_cctv_events[i].used
        )
        {
            return i;
        }
    }


    /*
     * 모두 사용 중이면
     * 이미 age 처리가 끝난 것 중 가장 오래된 것 교체
     */

    int oldest_index =
        -1;

    int64_t oldest_ms =
        INT64_MAX;


    for (
        int i = 0;
        i < CCTV_EVENT_TABLE_SIZE;
        i++
    )
    {
        if (
            s_cctv_events[i].age_resolved &&
            s_cctv_events[i].detected_ms <
            oldest_ms
        )
        {
            oldest_ms =
                s_cctv_events[i].detected_ms;

            oldest_index =
                i;
        }
    }


    if (
        oldest_index >= 0
    )
    {
        return oldest_index;
    }


    /*
     * 64개가 전부 아직 AGE_PENDING이면
     * 가장 오래된 것을 강제로 재사용.
     *
     * 매우 많은 사람이 1초 내 동시에 들어오는
     * 극단적인 상황에 대한 fallback.
     */

    oldest_ms =
        INT64_MAX;


    for (
        int i = 0;
        i < CCTV_EVENT_TABLE_SIZE;
        i++
    )
    {
        if (
            s_cctv_events[i].detected_ms <
            oldest_ms
        )
        {
            oldest_ms =
                s_cctv_events[i].detected_ms;

            oldest_index =
                i;
        }
    }


    ESP_LOGW(
        TAG,
        "CCTV event table full, replacing oldest pending event"
    );


    return oldest_index;
}


/* ============================================================
 * RADAR RECENT SEQ
 * ============================================================ */

static bool radar_seq_exists_locked(
    uint32_t seq
)
{
    for (
        uint8_t i = 0;
        i < s_radar_recent_count;
        i++
    )
    {
        if (
            s_radar_recent_seq[i] ==
            seq
        )
        {
            return true;
        }
    }


    return false;
}


static void radar_seq_store_locked(
    uint32_t seq
)
{
    s_radar_recent_seq[
        s_radar_recent_write
    ] = seq;


    s_radar_recent_write++;


    if (
        s_radar_recent_write >=
        RADAR_RECENT_SEQ_SIZE
    )
    {
        s_radar_recent_write =
            0;
    }


    if (
        s_radar_recent_count <
        RADAR_RECENT_SEQ_SIZE
    )
    {
        s_radar_recent_count++;
    }
}


/* ============================================================
 * INIT
 * ============================================================ */

void detection_manager_init(void)
{
    memset(
        &s_summary,
        0,
        sizeof(s_summary)
    );


    memset(
        s_cctv_events,
        0,
        sizeof(s_cctv_events)
    );


    memset(
        s_radar_recent_seq,
        0,
        sizeof(s_radar_recent_seq)
    );


    s_mutex =
        xSemaphoreCreateMutex();


    if (
        s_mutex ==
        NULL
    )
    {
        ESP_LOGE(
            TAG,
            "Mutex create failed"
        );

        abort();
    }


    /*
     * 일단 기본 감지 모드는 RADAR로 시작.
     * 필요하면 CCTV 기본으로 변경 가능.
     */

    s_summary.source =
        DETECTION_SOURCE_RADAR;


    s_summary.total_detected_count =
        0;


    /*
     * 부팅 직후부터 Sleep timer가 계산될 수 있도록
     * 현재 시간을 시작점으로 둠.
     */

    s_summary.last_detection_ms =
        get_now_ms();


    s_summary.latest_age_group =
        AGE_GROUP_UNKNOWN;


    s_summary.dominant_age_group =
        AGE_GROUP_UNKNOWN;


    ESP_LOGI(
        TAG,
        "Detection manager initialized / source=RADAR"
    );
}


/* ============================================================
 * SET SOURCE
 * ============================================================ */

void detection_manager_set_source(
    detection_source_t source
)
{
    if (
        source != DETECTION_SOURCE_RADAR &&
        source != DETECTION_SOURCE_CCTV
    )
    {
        return;
    }


    lock_manager();


    s_summary.source =
        source;


    /*
     * 소스 전환 직후 바로 Sleep 상태로 빠지는 것을
     * 막기 위해 timer 기준을 새로 시작.
     */

    s_summary.last_detection_ms =
        get_now_ms();


    unlock_manager();


    ESP_LOGI(
        TAG,
        "SOURCE -> %s",
        source == DETECTION_SOURCE_CCTV
            ? "CCTV"
            : "RADAR"
    );
}


/* ============================================================
 * GET SOURCE
 * ============================================================ */

detection_source_t detection_manager_get_source(void)
{
    detection_source_t source;


    lock_manager();

    source =
        s_summary.source;

    unlock_manager();


    return source;
}


/* ============================================================
 * CCTV NEW PERSON
 * ============================================================ */

bool detection_manager_cctv_new_person(
    uint32_t event_seq
)
{
    bool accepted =
        false;


    lock_manager();


    /*
     * CCTV가 선택되어 있지 않으면 무시
     */

    if (
        s_summary.source !=
        DETECTION_SOURCE_CCTV
    )
    {
        unlock_manager();

        return false;
    }


    /*
     * 같은 event_seq 재전송
     */

    if (
        find_cctv_event_locked(
            event_seq
        )
        >=
        0
    )
    {
        unlock_manager();


        ESP_LOGW(
            TAG,
            "CCTV NEW duplicate seq=%lu",
            (unsigned long)event_seq
        );


        return false;
    }


    int slot =
        allocate_cctv_event_locked();


    if (
        slot <
        0
    )
    {
        unlock_manager();

        return false;
    }


    s_cctv_events[slot].used =
        true;

    s_cctv_events[slot].age_resolved =
        false;

    s_cctv_events[slot].seq =
        event_seq;

    s_cctv_events[slot].detected_ms =
        get_now_ms();


    s_summary.total_detected_count++;


    s_summary.last_detection_ms =
        s_cctv_events[slot].detected_ms;


    uint32_t count =
        s_summary.total_detected_count;


    unlock_manager();


    ESP_LOGI(
        TAG,
        "CCTV NEW seq=%lu / total=%lu",
        (unsigned long)event_seq,
        (unsigned long)count
    );


    accepted =
        true;


    return accepted;
}


/* ============================================================
 * CCTV AGE RESULT
 * ============================================================ */

bool detection_manager_cctv_age_result(
    uint32_t event_seq,
    age_group_t age
)
{
    lock_manager();


    if (
        s_summary.source !=
        DETECTION_SOURCE_CCTV
    )
    {
        unlock_manager();

        return false;
    }


    int index =
        find_cctv_event_locked(
            event_seq
        );


    if (
        index <
        0
    )
    {
        unlock_manager();


        ESP_LOGW(
            TAG,
            "AGE result for unknown seq=%lu",
            (unsigned long)event_seq
        );


        return false;
    }


    /*
     * 같은 AGE_RESULT가 재전송된 경우
     */

    if (
        s_cctv_events[index].age_resolved
    )
    {
        unlock_manager();


        ESP_LOGW(
            TAG,
            "AGE duplicate seq=%lu",
            (unsigned long)event_seq
        );


        return false;
    }


    /*
     * 이 event는 이제 age 처리 완료
     */

    s_cctv_events[index].age_resolved =
        true;


    /*
     * 1초 판별 실패.
     *
     * 기존 음악 연령대를 유지해야 하므로
     * latest/dominant 통계는 건드리지 않음.
     */

    if (
        age ==
        AGE_GROUP_KEEP_CURRENT
    )
    {
        unlock_manager();


        ESP_LOGI(
            TAG,
            "AGE seq=%lu -> KEEP_CURRENT",
            (unsigned long)event_seq
        );


        return true;
    }


    if (
        !age_is_valid(
            age
        )
    )
    {
        unlock_manager();


        ESP_LOGW(
            TAG,
            "Invalid AGE=%02X seq=%lu",
            age,
            (unsigned long)event_seq
        );


        return false;
    }


    switch (age)
    {
        case AGE_GROUP_10S:
            s_summary.age_10_count++;
            break;

        case AGE_GROUP_20S:
            s_summary.age_20_count++;
            break;

        case AGE_GROUP_30S:
            s_summary.age_30_count++;
            break;

        case AGE_GROUP_40S:
            s_summary.age_40_count++;
            break;

        default:
            break;
    }


    s_summary.latest_age_group =
        age;


    update_dominant_age_locked();


    age_group_t latest =
        s_summary.latest_age_group;


    age_group_t dominant =
        s_summary.dominant_age_group;


    unlock_manager();


    ESP_LOGI(
        TAG,
        "AGE seq=%lu -> %d / latest=%d dominant=%d",
        (unsigned long)event_seq,
        age,
        latest,
        dominant
    );


    return true;
}


/* ============================================================
 * RADAR NEW PERSON
 * ============================================================ */

bool detection_manager_radar_new_person(
    uint32_t seq
)
{
    lock_manager();


    if (
        s_summary.source !=
        DETECTION_SOURCE_RADAR
    )
    {
        unlock_manager();

        return false;
    }


    /*
     * 재전송 중복
     */

    if (
        radar_seq_exists_locked(
            seq
        )
    )
    {
        unlock_manager();


        ESP_LOGW(
            TAG,
            "RADAR duplicate seq=%lu",
            (unsigned long)seq
        );


        return false;
    }


    radar_seq_store_locked(
        seq
    );


    s_summary.total_detected_count++;


    s_summary.last_detection_ms =
        get_now_ms();


    uint32_t count =
        s_summary.total_detected_count;


    unlock_manager();


    ESP_LOGI(
        TAG,
        "RADAR NEW seq=%lu / total=%lu",
        (unsigned long)seq,
        (unsigned long)count
    );


    return true;
}


/* ============================================================
 * GET SUMMARY
 * ============================================================ */

void detection_manager_get_summary(
    detection_summary_t *summary
)
{
    if (
        summary ==
        NULL
    )
    {
        return;
    }


    lock_manager();


    memcpy(
        summary,
        &s_summary,
        sizeof(
            detection_summary_t
        )
    );


    unlock_manager();
}