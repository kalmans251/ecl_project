idf_component_register(
    SRCS
        "hello-wroom.c"

        "protocol.c"
        "protocol_parser.c"

        "router.c"

        "p4_uart.c"
        "p4_task.c"

        "controller.c"

        "s3_ble.c"
        "s3_task.c"

        "sd_card.c"

        "audio_output.c"
        "music_player.c"
        "emergency_alert.c"

        "playlist_manager.c"
        "sd_manager.c"

        
    INCLUDE_DIRS
        "."

    REQUIRES
        esp_driver_uart

        esp_driver_spi
        esp_driver_sdspi

        esp_driver_i2s

        fatfs
        sdmmc

        bt
        nvs_flash
)