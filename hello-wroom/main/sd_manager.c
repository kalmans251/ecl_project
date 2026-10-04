#include "sd_manager.h"

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "esp_log.h"

#include "sd_card.h"
#include "music_player.h"
#include "playlist_manager.h"


static const char *TAG =
    "SD_MANAGER";


/* ============================================================
 * CONFIG
 * ============================================================ */

/*
 * SD 상태 확인 주기.
 */
#define SD_CHECK_INTERVAL_MS     1000


/*
 * STOP 명령 이후 player가 파일을 닫을 때까지 기다리는
 * 최대 시간.
 */
#define PLAYER_STOP_TIMEOUT_MS   2000


/* ============================================================
 * STATE
 * ============================================================ */

static TaskHandle_t
    s_task =
        NULL;


static volatile bool
    s_ready =
        false;


/* ============================================================
 * WAIT PLAYER IDLE
 * ============================================================ */

static bool wait_player_idle(void)
{
    int elapsed =
        0;


    while (
        music_player_get_state()
        !=
        MUSIC_PLAYER_IDLE
    )
    {
        if (
            elapsed >=
            PLAYER_STOP_TIMEOUT_MS
        )
        {
            ESP_LOGW(
                TAG,
                "Player stop timeout"
            );


            return false;
        }


        vTaskDelay(
            pdMS_TO_TICKS(
                50
            )
        );


        elapsed +=
            50;
    }


    return true;
}


/* ============================================================
 * HANDLE REMOVAL
 * ============================================================ */

static bool handle_sd_removed(void)
{
    ESP_LOGW(
        TAG,
        "SD card removed"
    );


    /*
     * 이 순간부터 새로운 START / NEXT 금지.
     */
    s_ready =
        false;


    /*
     * 재생 또는 PAUSE 중이면 파일 descriptor가 살아있으므로
     * 먼저 player에게 STOP 요청.
     */
    if (
        music_player_get_state()
        !=
        MUSIC_PLAYER_IDLE
    )
    {
        ESP_LOGI(
            TAG,
            "Stopping music before SD unmount"
        );


        music_player_stop();


        if (
            !wait_player_idle()
        )
        {
            /*
             * 아직 파일을 닫지 못했다.
             *
             * 강제로 unmount하지 않고
             * 다음 loop에서 다시 처리한다.
             */
            return false;
        }
    }


    /*
     * player가 파일을 완전히 닫은 뒤 unmount.
     */
    sd_card_deinit();


    ESP_LOGI(
        TAG,
        "SD removal handling complete"
    );


    return true;
}


/* ============================================================
 * TRY MOUNT
 * ============================================================ */

static bool try_mount_sd(void)
{
    ESP_LOGI(
        TAG,
        "Trying SD mount..."
    );


    if (
        !sd_card_init()
    )
    {
        return false;
    }


    ESP_LOGI(
        TAG,
        "SD mount success"
    );


    /*
     * 새 카드 또는 변경된 카드를 다시 스캔.
     */
    if (
        !playlist_manager_rescan()
    )
    {
        ESP_LOGE(
            TAG,
            "Playlist rescan failed"
        );


        sd_card_deinit();


        return false;
    }


    s_ready =
        true;


    ESP_LOGI(
        TAG,
        "SD READY"
    );


    return true;
}


/* ============================================================
 * TASK
 * ============================================================ */

static void sd_manager_task(
    void *arg
)
{
    (void)arg;


    ESP_LOGI(
        TAG,
        "SD manager task started"
    );


    while (1)
    {
        /*
         * ====================================================
         * 현재 mount된 상태
         * ====================================================
         */
        if (
            sd_card_is_mounted()
        )
        {
            /*
             * PLAYING 중에는 음악 player 자체가 계속 SD read를
             * 하고 있다.
             *
             * 재생 중 카드가 제거되면 player read 에러가 먼저
             * 발생하고 IDLE로 빠지므로, 동시에 별도 status
             * command를 날리지 않는다.
             */
            if (
                music_player_get_state()
                !=
                MUSIC_PLAYER_PLAYING
            )
            {
                if (
                    !sd_card_check_health()
                )
                {
                    handle_sd_removed();
                }
            }
        }

        /*
         * ====================================================
         * 현재 unmount 상태
         * ====================================================
         */
        else
        {
            s_ready =
                false;


            try_mount_sd();
        }


        vTaskDelay(
            pdMS_TO_TICKS(
                SD_CHECK_INTERVAL_MS
            )
        );
    }
}


/* ============================================================
 * INIT
 * ============================================================ */

bool sd_manager_init(void)
{
    if (
        s_task != NULL
    )
    {
        return true;
    }


    /*
     * 부팅 시 이미 SD 초기화 + playlist scan이 끝났다면
     * 즉시 READY.
     */
    s_ready =
        sd_card_is_mounted();


    BaseType_t result =
        xTaskCreate(
            sd_manager_task,

            "sd_manager",

            4096,

            NULL,

            8,

            &s_task
        );


    if (
        result != pdPASS
    )
    {
        s_task =
            NULL;


        return false;
    }


    ESP_LOGI(
        TAG,
        "SD manager initialized / ready=%d",
        s_ready
    );


    return true;
}


/* ============================================================
 * READY
 * ============================================================ */

bool sd_manager_is_ready(void)
{
    return s_ready;
}