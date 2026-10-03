idf_component_register(SRCS "hello_world_main.c" "plc_uart.c" "protocol.c" "protocol_parser.c" "plc_uart.c" "plc_task.c" "wroom_uart.c" "wroom_task.c" "router.c" "p4_controller.c" "system_state.c" "led_task.c" "power_control.c" "power_control.c" "projector_control.c" "detection_manager.c" "sleep_manager.c" "call_manager.c"
                       PRIV_REQUIRES spi_flash esp_driver_uart esp_timer esp_driver_gpio
                       INCLUDE_DIRS "")
