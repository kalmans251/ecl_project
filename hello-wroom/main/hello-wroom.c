#include <stdio.h>

#include "board_config.h"

#include "controller.h"

#include "music_player.h"

#include "p4_task.h"
#include "p4_uart.h"

#include "router.h"

#include "s3_ble.h"
#include "s3_task.h"

#include "sd_card.h"

#include "esp_log.h"

#include "playlist_manager.h"
#include "sd_manager.h"

static const char *TAG =
    "MAIN";


void app_main(void)
{
    printf(
        "\n"
        "========================================\n"
        " ESP32-WROOM START\n"
        " RAILING ID : %d\n"
        " PROTOCOL   : SERVICE + CRC16\n"
        "========================================\n",
        RAILING_ID
    );


    /* ========================================================
     * P4 UART
     * ======================================================== */

    if (
        !p4_uart_init()
    )
    {
        ESP_LOGE(
            TAG,
            "P4 UART init failed"
        );


        return;
    }


    /* ========================================================
     * CONTROLLER
     * ======================================================== */

    if (
        !controller_init()
    )
    {
        ESP_LOGE(
            TAG,
            "Controller init failed"
        );


        return;
    }


    /* ========================================================
     * P4 TASK
     * ======================================================== */

    if (
        !p4_task_init()
    )
    {
        ESP_LOGE(
            TAG,
            "P4 task init failed"
        );


        return;
    }


    /* ========================================================
     * S3 TASK
     * ======================================================== */

    if (
        !s3_task_init()
    )
    {
        ESP_LOGE(
            TAG,
            "S3 task init failed"
        );


        return;
    }


    /* ========================================================
     * ROUTER
     * ======================================================== */

    if (
        !router_init()
    )
    {
        ESP_LOGE(
            TAG,
            "Router init failed"
        );


        return;
    }


    /* ========================================================
     * BLE
     * ======================================================== */

    if (
        !s3_ble_init()
    )
    {
        ESP_LOGE(
            TAG,
            "S3 BLE init failed"
        );


        return;
    }


    /* ========================================================
    * MUSIC PLAYER
    *
    * SD가 없어도 player task 자체는 살아 있어야 한다.
    * ======================================================== */

    if (
        !music_player_init()
    )
    {
        ESP_LOGE(
            TAG,
            "Music player init failed"
        );


        return;
    }


    /* ========================================================
    * SD
    *
    * SD가 없어도 WROOM 전체 부팅은 계속한다.
    * sd_manager가 나중에 자동 재연결한다.
    * ======================================================== */

    bool sd_ready =
        sd_card_init();


    if (
        sd_ready
    )
    {
        ESP_LOGI(
            TAG,
            "Initial SD mount success"
        );


        if (
            !playlist_manager_init()
        )
        {
            ESP_LOGW(
                TAG,
                "Initial playlist scan failed"
            );


            sd_card_deinit();

            sd_ready =
                false;
        }
    }
    else
    {
        ESP_LOGW(
            TAG,
            "No SD card at boot - waiting for insertion"
        );
    }


    /* ========================================================
    * SD MANAGER
    * ======================================================== */

    if (
        !sd_manager_init()
    )
    {
        ESP_LOGE(
            TAG,
            "SD manager init failed"
        );


        return;
    }
}