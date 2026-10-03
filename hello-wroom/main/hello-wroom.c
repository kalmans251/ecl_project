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
     * SD
     * ======================================================== */

    if (
        !sd_card_init()
    )
    {
        ESP_LOGE(
            TAG,
            "SD init failed"
        );


        return;
    }


    /* ========================================================
     * MUSIC PLAYER
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


    ESP_LOGI(
        TAG,
        "================================"
    );


    ESP_LOGI(
        TAG,
        "WROOM SYSTEM READY"
    );


    ESP_LOGI(
        TAG,
        "Waiting MUSIC command from P4"
    );


    ESP_LOGI(
        TAG,
        "================================"
    );
}