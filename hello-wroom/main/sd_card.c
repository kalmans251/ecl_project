#include "sd_card.h"

#include <dirent.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>

#include "board_config.h"

#include "driver/sdspi_host.h"
#include "driver/spi_master.h"

#include "esp_err.h"
#include "esp_log.h"
#include "esp_vfs_fat.h"


static const char *TAG =
    "SD_CARD";


static sdmmc_card_t *s_card =
    NULL;


static bool s_mounted =
    false;


static bool s_spi_bus_initialized =
    false;


/* ============================================================
 * INIT
 * ============================================================ */

bool sd_card_init(void)
{
    if (
        s_mounted
    )
    {
        ESP_LOGW(
            TAG,
            "SD already mounted"
        );


        return true;
    }


    spi_bus_config_t bus_config =
    {
        .mosi_io_num =
            PIN_NUM_MOSI,

        .miso_io_num =
            PIN_NUM_MISO,

        .sclk_io_num =
            PIN_NUM_CLK,

        .quadwp_io_num =
            -1,

        .quadhd_io_num =
            -1,


        /*
         * MP3 streaming용.
         */

        .max_transfer_sz =
            64 *
            1024,
    };


    esp_err_t err =
        spi_bus_initialize(
            SD_SPI_HOST,

            &bus_config,

            SPI_DMA_CH_AUTO
        );


    if (
        err != ESP_OK &&
        err != ESP_ERR_INVALID_STATE
    )
    {
        ESP_LOGE(
            TAG,
            "spi_bus_initialize failed: %s",
            esp_err_to_name(err)
        );


        return false;
    }


    s_spi_bus_initialized =
        err ==
        ESP_OK;


    /* ========================================================
     * HOST
     * ======================================================== */

    sdmmc_host_t host =
        SDSPI_HOST_DEFAULT();


    host.slot =
        SD_SPI_HOST;


    /* ========================================================
     * SLOT
     * ======================================================== */

    sdspi_device_config_t slot_config =
        SDSPI_DEVICE_CONFIG_DEFAULT();


    slot_config.gpio_cs =
        PIN_NUM_CS;


    slot_config.host_id =
        SD_SPI_HOST;


    /* ========================================================
     * FAT
     * ======================================================== */

    esp_vfs_fat_sdmmc_mount_config_t mount_config =
    {
        .format_if_mount_failed =
            false,

        .max_files =
            10,

        .allocation_unit_size =
            16 *
            1024,
    };


    ESP_LOGI(
        TAG,
        "Mounting SD card..."
    );


    err =
        esp_vfs_fat_sdspi_mount(
            SD_MOUNT_POINT,

            &host,

            &slot_config,

            &mount_config,

            &s_card
        );


    if (
        err !=
        ESP_OK
    )
    {
        ESP_LOGE(
            TAG,
            "SD mount failed: %s",
            esp_err_to_name(err)
        );


        if (
            s_spi_bus_initialized
        )
        {
            spi_bus_free(
                SD_SPI_HOST
            );


            s_spi_bus_initialized =
                false;
        }


        s_card =
            NULL;


        s_mounted =
            false;


        return false;
    }


    s_mounted =
        true;


    ESP_LOGI(
        TAG,
        "SD mounted: %s",
        SD_MOUNT_POINT
    );


    size_t actual_max_transfer =
        0;


    esp_err_t max_err =
        spi_bus_get_max_transaction_len(
            SD_SPI_HOST,

            &actual_max_transfer
        );


    if (
        max_err ==
        ESP_OK
    )
    {
        ESP_LOGI(
            TAG,
            "SPI actual max transfer = %u bytes",
            (unsigned)actual_max_transfer
        );
    }


    sd_card_print_info();


    return true;
}


/* ============================================================
 * DEINIT
 * ============================================================ */

void sd_card_deinit(void)
{
    if (
        s_mounted
    )
    {
        esp_vfs_fat_sdcard_unmount(
            SD_MOUNT_POINT,

            s_card
        );


        s_card =
            NULL;


        s_mounted =
            false;
    }


    if (
        s_spi_bus_initialized
    )
    {
        spi_bus_free(
            SD_SPI_HOST
        );


        s_spi_bus_initialized =
            false;
    }


    ESP_LOGI(
        TAG,
        "SD unmounted"
    );
}


/* ============================================================
 * STATE
 * ============================================================ */

bool sd_card_is_mounted(void)
{
    return s_mounted;
}


sdmmc_card_t *sd_card_get(void)
{
    return s_card;
}

/* ============================================================
 * HEALTH CHECK
 * ============================================================ */

bool sd_card_check_health(void)
{
    if (
        !s_mounted ||
        s_card == NULL
    )
    {
        return false;
    }


    esp_err_t err =
        sdmmc_get_status(
            s_card
        );


    if (
        err != ESP_OK
    )
    {
        ESP_LOGW(
            TAG,
            "SD health check failed: %s",
            esp_err_to_name(err)
        );


        return false;
    }


    return true;
}

/* ============================================================
 * PRINT INFO
 * ============================================================ */

void sd_card_print_info(void)
{
    if (
        !s_mounted ||
        s_card == NULL
    )
    {
        return;
    }


    sdmmc_card_print_info(
        stdout,

        s_card
    );
}


/* ============================================================
 * LIST
 * ============================================================ */

void sd_card_list_directory(
    const char *path
)
{
    if (
        !s_mounted
    )
    {
        return;
    }


    DIR *dir =
        opendir(
            path
        );


    if (
        dir ==
        NULL
    )
    {
        ESP_LOGW(
            TAG,
            "Cannot open directory: %s",
            path
        );


        return;
    }


    ESP_LOGI(
        TAG,
        "Directory: %s",
        path
    );


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
            strcmp(
                entry->d_name,
                "."
            )
            ==
            0
            ||
            strcmp(
                entry->d_name,
                ".."
            )
            ==
            0
        )
        {
            continue;
        }


        char full_path[
            256
        ];


        size_t path_len =
            strlen(
                path
            );


        size_t name_len =
            strlen(
                entry->d_name
            );


        if (
            path_len +
            1 +
            name_len +
            1 >
            sizeof(full_path)
        )
        {
            continue;
        }


        memcpy(
            full_path,

            path,

            path_len
        );


        full_path[
            path_len
        ] =
            '/';


        memcpy(
            &full_path[
                path_len +
                1
            ],

            entry->d_name,

            name_len
        );


        full_path[
            path_len +
            1 +
            name_len
        ] =
            '\0';


        struct stat st;


        if (
            stat(
                full_path,

                &st
            )
            !=
            0
        )
        {
            continue;
        }


        if (
            S_ISDIR(
                st.st_mode
            )
        )
        {
            ESP_LOGI(
                TAG,
                "[DIR ] %s",
                entry->d_name
            );
        }
        else
        {
            ESP_LOGI(
                TAG,
                "[FILE] %s (%ld bytes)",
                entry->d_name,
                (long)st.st_size
            );
        }
    }


    closedir(
        dir
    );
}