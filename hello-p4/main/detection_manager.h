#pragma once

#include <stdbool.h>
#include <stdint.h>


/* ============================================================
 * DETECTION SOURCE
 *
 * 반드시 둘 중 하나만 활성화
 * ============================================================ */

typedef enum
{
    DETECTION_SOURCE_RADAR = 0x00,
    DETECTION_SOURCE_CCTV  = 0x01

} detection_source_t;


/* ============================================================
 * DETECTION EVENTS
 * ============================================================ */

typedef enum
{
    DETECT_EVENT_CCTV_NEW_PERSON = 0x01,

    DETECT_EVENT_CCTV_AGE_RESULT = 0x02,

    DETECT_EVENT_RADAR_NEW_PERSON = 0x03

} detection_event_t;


/* ============================================================
 * AGE
 *
 * 현재 음악 폴더 기준:
 * 10 / 20 / 30 / 40대
 *
 * KEEP_CURRENT:
 * 나이 판별 실패
 * 기존 음악 연령대를 그대로 유지
 * ============================================================ */

typedef enum
{
    AGE_GROUP_UNKNOWN = 0x00,

    AGE_GROUP_10S = 0x01,
    AGE_GROUP_20S = 0x02,
    AGE_GROUP_30S = 0x03,
    AGE_GROUP_40S = 0x04,

    AGE_GROUP_KEEP_CURRENT = 0xFF

} age_group_t;


/* ============================================================
 * SUMMARY
 * ============================================================ */

typedef struct
{
    detection_source_t source;


    /*
     * 현재 source에서 인정된
     * 누적 신규 포착 인원 수
     *
     * 현재 현장에 몇 명 남아있는지를 의미하지 않음.
     */
    uint32_t total_detected_count;


    /*
     * 마지막 신규 사람 포착 시각
     */
    int64_t last_detection_ms;


    /*
     * CCTV age statistics
     */

    uint32_t age_10_count;
    uint32_t age_20_count;
    uint32_t age_30_count;
    uint32_t age_40_count;


    /*
     * 가장 최근 정상 판별된 연령대
     */
    age_group_t latest_age_group;


    /*
     * 가장 많이 판별된 연령대
     */
    age_group_t dominant_age_group;

} detection_summary_t;


/* ============================================================
 * INIT
 * ============================================================ */

void detection_manager_init(void);


/* ============================================================
 * SOURCE
 * ============================================================ */

void detection_manager_set_source(
    detection_source_t source
);

detection_source_t detection_manager_get_source(void);


/* ============================================================
 * CCTV
 * ============================================================ */

bool detection_manager_cctv_new_person(
    uint32_t event_seq
);


bool detection_manager_cctv_age_result(
    uint32_t event_seq,
    age_group_t age
);


/* ============================================================
 * RADAR
 * ============================================================ */

bool detection_manager_radar_new_person(
    uint32_t seq
);


/* ============================================================
 * STATE
 * ============================================================ */

void detection_manager_get_summary(
    detection_summary_t *summary
);