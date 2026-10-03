#include "sleep_manager.h"

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"

#include "esp_log.h"
#include "esp_timer.h"

#include "system_state.h"
#include "projector_control.h"


static const char *TAG =
    "SLEEP";


/* ============================================================
 * CONFIG
 * ============================================================ */

/*
 * 마지막 신규 포착 이후 10초
 */
#define SLEEP_IDLE_TIMEOUT_MS        10000


/*
 * Pi가 CCTV 나이 판별 실패 시 1초 후 KEEP_CURRENT를
 * 보내기로 했지만, 통신 유실 등에 대비한 P4 fallback.
 */
#define CCTV_AGE_WAIT_TIMEOUT_MS     2000


/* ============================================================
 * INTERNAL STATE
 * ============================================================ */

static SemaphoreHandle_t
    s_mutex =
        NULL;


static activity_state_t
    s_activity =
        ACTIVITY_ACTIVE;


/*
 * Sleep 기능을 켠 시각.
 *
 * Detection Manager의 last_detection_ms가 아주 오래됐더라도
 * Sleep 기능을 켜자마자 즉시 잠들지 않도록 사용.
 */
static int64_t
    s_enabled_since_ms =
        0;


/*
 * SLEEPING 상태에서 CCTV 사람이 새로 발견되었을 때
 * 어떤 AGE_RESULT를 기다리는지.
 */
static uint32_t
    s_wait_age_seq =
        0;


static int64_t
    s_wait_age_started_ms =
        0;


/* ============================================================
 * TIME
 * ============================================================ */

static int64_t now_ms(void)
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
 * RESTORE OUTPUTS
 *
 * 논리적인 enabled 상태는 건드리지 않는다.
 * ============================================================ */

static void restore_outputs(void)
{
    p4_system_state_t state;


    /*
     * LED:
     *
     * led_task가 sleep_active를 직접 보고 있으므로
     * false만 만들어주면 기존 모드로 자동 복귀.
     */

    system_state_set_sleep_active(
        false
    );


    system_state_get(
        &state
    );




    /*
     * Projector:
     *
     * 원래 사용자가 ON으로 해놨던 경우에만 복귀.
     */
    if (
        state.projector_enabled
    )
    {
        projector_control_set(
            true
        );
    }


    ESP_LOGI(
        TAG,
        "OUTPUT RESTORE"
    );
}


/* ============================================================
 * PHYSICAL SLEEP
 * ============================================================ */

static void enter_sleeping(void)
{
    p4_system_state_t state;


    system_state_get(
        &state
    );


    /*
     * LED 실제 출력 OFF.
     *
     * led_enabled / led_mode는 유지.
     */
    system_state_set_sleep_active(
        true
    );


    /*
     * Projector도 실제 출력만 OFF.
     *
     * projector_enabled는 그대로 유지한다.
     */
    if (
        state.projector_enabled
    )
    {
        projector_control_set(
            false
        );
    }


    lock_manager();

    s_activity =
        ACTIVITY_SLEEPING;

    s_wait_age_seq =
        0;

    s_wait_age_started_ms =
        0;

    unlock_manager();


    ESP_LOGI(
        TAG,
        "STATE -> SLEEPING"
    );


    /*
     * MUSIC:
     *
     * 여기까지 들어오는 시점에는
     * 이미 곡이 FINISHED 되었거나
     * 애초에 음악이 재생 중이 아니어야 한다.
     *
     * 따라서 음악을 강제로 STOP/PAUSE 하지 않는다.
     *
     * 단지 다음 곡을 시작하지 않을 뿐이다.
     */
}


/* ============================================================
 * ENTER ACTIVE
 * ============================================================ */

static void enter_active(void)
{
    restore_outputs();


    lock_manager();

    s_activity =
        ACTIVITY_ACTIVE;

    s_wait_age_seq =
        0;

    s_wait_age_started_ms =
        0;

    unlock_manager();


    ESP_LOGI(
        TAG,
        "STATE -> ACTIVE"
    );
}


/* ============================================================
 * INIT
 * ============================================================ */

void sleep_manager_init(void)
{
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


    s_activity =
        ACTIVITY_ACTIVE;


    s_enabled_since_ms =
        now_ms();


    ESP_LOGI(
        TAG,
        "Sleep manager initialized"
    );
}


/* ============================================================
 * ENABLE / DISABLE
 * ============================================================ */

void sleep_manager_set_enabled(
    bool enabled
)
{
    system_state_set_sleep_mode_enabled(
        enabled
    );


    if (
        enabled
    )
    {
        lock_manager();

        s_activity =
            ACTIVITY_ACTIVE;

        s_enabled_since_ms =
            now_ms();

        s_wait_age_seq =
            0;

        s_wait_age_started_ms =
            0;

        unlock_manager();


        system_state_set_sleep_active(
            false
        );


        ESP_LOGI(
            TAG,
            "SLEEP MODE ENABLED"
        );
    }
    else
    {
        /*
         * Sleep 기능 자체를 끄면
         * 어떤 상태였든 정상 출력으로 복귀.
         */

        enter_active();


        ESP_LOGI(
            TAG,
            "SLEEP MODE DISABLED"
        );
    }
}


/* ============================================================
 * NEW DETECTION
 * ============================================================ */

void sleep_manager_on_new_detection(
    detection_source_t source,
    uint32_t seq
)
{
    p4_system_state_t system;


    system_state_get(
        &system
    );


    if (
        !system.sleep_mode_enabled ||
        system.call_active
    )
    {
        return;
    }


    lock_manager();


    activity_state_t current =
        s_activity;


    /*
     * ACTIVE 상태에서는 Detection Manager가
     * last_detection_ms만 갱신하면 충분.
     */
    if (
        current ==
        ACTIVITY_ACTIVE
    )
    {
        unlock_manager();

        return;
    }


    /*
     * 곡 종료 대기 중 사람이 다시 발견되면
     * Sleep 예정 취소.
     *
     * 현재 곡은 끊지 않고 그대로 재생.
     */
    if (
        current ==
        ACTIVITY_SLEEP_PENDING
    )
    {
        s_activity =
            ACTIVITY_ACTIVE;

        unlock_manager();


        ESP_LOGI(
            TAG,
            "NEW PERSON -> cancel SLEEP_PENDING"
        );


        return;
    }


    /*
     * 실제 Sleep 상태
     */
    if (
        current ==
        ACTIVITY_SLEEPING
    )
    {
        /*
         * RADAR
         *
         * 나이를 기다릴 필요가 없음.
         */
        if (
            source ==
            DETECTION_SOURCE_RADAR
        )
        {
            unlock_manager();


            ESP_LOGI(
                TAG,
                "RADAR wake"
            );


            enter_active();


            /*
             * 여기서 나중에:
             * 기본 Radar 음악 시작 명령
             * 을 Music Manager로 보낼 예정.
             */


            return;
        }


        /*
         * CCTV
         *
         * 나이가 판별될 때까지
         * 실제 출력은 Sleep 상태 유지.
         */
        if (
            source ==
            DETECTION_SOURCE_CCTV
        )
        {
            s_activity =
                ACTIVITY_WAIT_AGE;

            s_wait_age_seq =
                seq;

            s_wait_age_started_ms =
                now_ms();


            unlock_manager();


            ESP_LOGI(
                TAG,
                "CCTV wake pending AGE seq=%lu",
                (unsigned long)seq
            );


            return;
        }
    }


    /*
     * WAIT_AGE 상태에서 추가 CCTV 사람이 들어와도
     * 첫 번째 wake seq를 그대로 기다린다.
     *
     * 추가 사람의 AGE_RESULT는 Detection Manager에서
     * 정상적으로 통계에 반영된다.
     */

    unlock_manager();
}


/* ============================================================
 * CCTV AGE RESULT
 * ============================================================ */

void sleep_manager_on_cctv_age_result(
    uint32_t seq,
    age_group_t age
)
{
    p4_system_state_t system;


    system_state_get(
        &system
    );


    if (
        !system.sleep_mode_enabled ||
        system.call_active
    )
    {
        return;
    }


    lock_manager();


    if (
        s_activity !=
        ACTIVITY_WAIT_AGE
    )
    {
        unlock_manager();

        return;
    }


    /*
     * Sleep 해제를 발생시킨 사람의 AGE 결과만
     * wake trigger로 사용.
     */

    if (
        seq !=
        s_wait_age_seq
    )
    {
        unlock_manager();

        return;
    }


    unlock_manager();


    if (
        age ==
        AGE_GROUP_KEEP_CURRENT
    )
    {
        ESP_LOGI(
            TAG,
            "WAKE AGE=KEEP_CURRENT"
        );
    }
    else
    {
        ESP_LOGI(
            TAG,
            "WAKE AGE=%d",
            age
        );
    }


    /*
     * LED / Projector 복구.
     */
    enter_active();


    /*
     * 다음 단계 Music Manager에서:
     *
     * AGE 정상:
     * 해당 나잇대 음악 START
     *
     * KEEP_CURRENT:
     * 기존 music age 음악 START
     *
     * 를 처리하게 됨.
     */
}


/* ============================================================
 * MUSIC FINISHED
 * ============================================================ */

void sleep_manager_on_music_finished(void)
{
    p4_system_state_t system;


    system_state_get(
        &system
    );


    if (
        !system.sleep_mode_enabled ||
        system.call_active
    )
    {
        return;
    }


    lock_manager();


    activity_state_t current =
        s_activity;


    unlock_manager();


    /*
     * 우리가 기다리던 곡이 끝난 경우.
     */
    if (
        current ==
        ACTIVITY_SLEEP_PENDING
    )
    {
        detection_summary_t detection;


        detection_manager_get_summary(
            &detection
        );


        int64_t current_ms =
            now_ms();


        int64_t reference_ms =
            detection.last_detection_ms;


        if (
            s_enabled_since_ms >
            reference_ms
        )
        {
            reference_ms =
                s_enabled_since_ms;
        }


        if (
            current_ms -
            reference_ms
            >=
            SLEEP_IDLE_TIMEOUT_MS
        )
        {
            /*
             * 곡이 끝날 때까지도
             * 새 사람이 발견되지 않았음.
             */

            enter_sleeping();
        }
        else
        {
            /*
             * 곡이 끝나기 전에 사람이 발견됨.
             */

            enter_active();
        }
    }
}


/* ============================================================
 * SOURCE CHANGE
 * ============================================================ */

void sleep_manager_reset_activity(void)
{
    s_enabled_since_ms =
        now_ms();


    enter_active();


    ESP_LOGI(
        TAG,
        "Activity reset by source change"
    );
}


/* ============================================================
 * GET STATE
 * ============================================================ */

activity_state_t sleep_manager_get_state(void)
{
    activity_state_t state;


    lock_manager();

    state =
        s_activity;

    unlock_manager();


    return state;
}


/* ============================================================
 * TASK
 * ============================================================ */

void sleep_manager_task(
    void *arg
)
{
    (void)arg;


    while (1)
    {
        p4_system_state_t system;


        system_state_get(
            &system
        );
        /*
        * 통화 중에는 Sleep 판단 중지.
        *
        * Detection Manager 자체는 계속 동작하므로
        * last_detection_ms는 계속 갱신될 수 있음.
        */
        if (
            system.call_active
        )
        {
            vTaskDelay(
                pdMS_TO_TICKS(100)
            );

            continue;
        }


        /*
         * Sleep 기능 자체가 OFF
         */
        if (
            !system.sleep_mode_enabled
        )
        {
            vTaskDelay(
                pdMS_TO_TICKS(100)
            );

            continue;
        }


        activity_state_t activity =
            sleep_manager_get_state();


        /*
         * ====================================================
         * ACTIVE
         * ====================================================
         */

        if (
            activity ==
            ACTIVITY_ACTIVE
        )
        {
            detection_summary_t detection;


            detection_manager_get_summary(
                &detection
            );


            int64_t current =
                now_ms();


            int64_t reference =
                detection.last_detection_ms;


            /*
             * Sleep 기능을 최근에 켰다면
             * enable 시간을 기준으로 최소 10초 기다림.
             */

            if (
                s_enabled_since_ms >
                reference
            )
            {
                reference =
                    s_enabled_since_ms;
            }


            if (
                current -
                reference
                >=
                SLEEP_IDLE_TIMEOUT_MS
            )
            {
                /*
                 * 10초 신규 사람 없음.
                 */

                if (
                    system.music_playing
                )
                {
                    /*
                     * 현재 곡은 끊지 않는다.
                     */

                    lock_manager();

                    s_activity =
                        ACTIVITY_SLEEP_PENDING;

                    unlock_manager();


                    ESP_LOGI(
                        TAG,
                        "STATE -> SLEEP_PENDING"
                    );
                }
                else
                {
                    /*
                     * 재생 중인 곡 없음.
                     * 바로 Sleep.
                     */

                    enter_sleeping();
                }
            }
        }


        /*
         * ====================================================
         * SLEEP_PENDING
         *
         * FINISHED 이벤트를 기다리지만,
         * music_playing이 false가 된 경우도 보호.
         * ====================================================
         */

        else if (
            activity ==
            ACTIVITY_SLEEP_PENDING
        )
        {
            if (
                !system.music_playing
            )
            {
                detection_summary_t detection;


                detection_manager_get_summary(
                    &detection
                );


                if (
                    now_ms() -
                    detection.last_detection_ms
                    >=
                    SLEEP_IDLE_TIMEOUT_MS
                )
                {
                    enter_sleeping();
                }
                else
                {
                    enter_active();
                }
            }
        }


        /*
         * ====================================================
         * WAIT AGE fallback
         * ====================================================
         */

        else if (
            activity ==
            ACTIVITY_WAIT_AGE
        )
        {
            int64_t elapsed;


            lock_manager();

            elapsed =
                now_ms()
                -
                s_wait_age_started_ms;

            unlock_manager();


            /*
             * Pi가 1초 후 KEEP_CURRENT를 보내기로 했지만
             * 해당 패킷까지 유실되는 상황에 대비.
             */

            if (
                elapsed >=
                CCTV_AGE_WAIT_TIMEOUT_MS
            )
            {
                ESP_LOGW(
                    TAG,
                    "AGE wait timeout -> KEEP_CURRENT wake"
                );


                enter_active();


                /*
                 * 다음 Music Manager 단계에서는
                 * 기존 나잇대 음악을 재생하도록 연결.
                 */
            }
        }


        /*
         * 100ms 주기로 충분.
         */
        vTaskDelay(
            pdMS_TO_TICKS(100)
        );
    }
}