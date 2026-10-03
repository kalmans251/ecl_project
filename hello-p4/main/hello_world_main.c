#include <stdio.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "board_config.h"

#include "router.h"

#include "plc_uart.h"
#include "plc_task.h"

#include "wroom_uart.h"
#include "wroom_task.h"

#include "p4_controller.h"

#include "system_state.h"
#include "led_task.h"

#include "power_control.h"
#include "projector_control.h"

#include "detection_manager.h"

#include "sleep_manager.h"

#include "call_manager.h"

void app_main(void)
{
    printf("\n");
    printf("========================================\n");
    printf(" ESP32-P4 START\n");
    printf(" RAILING ID : %d\n", RAILING_ID);
    printf(" PROTOCOL   : SERVICE + CRC16\n");
    printf("========================================\n");


    /* Queue / Router */

    router_init();


    /* Hardware */

    plc_uart_init();

    wroom_uart_init();

    system_state_init();

    detection_manager_init();

    power_control_init();

    projector_control_init();

    led_task_init();

    call_manager_init();

    sleep_manager_init();

    /* PLC */

    xTaskCreatePinnedToCore(
        plc_task,
        "plc_task",
        4096,
        NULL,
        15,
        NULL,
        0
    );


    /* WROOM */

    xTaskCreatePinnedToCore(
        wroom_task,
        "wroom_task",
        4096,
        NULL,
        13,
        NULL,
        1
    );


    /* Router */

    xTaskCreatePinnedToCore(
        router_task,
        "router_task",
        4096,
        NULL,
        12,
        NULL,
        1
    );


    /* P4 Controller */

    xTaskCreatePinnedToCore(
        p4_controller_task,
        "p4_controller",
        4096,
        NULL,
        10,
        NULL,
        1
    );

    /* LED task */
    xTaskCreate(
    led_task,
    "led_task",
    4096,
    NULL,
    8,
    NULL
    );

    /* SLEEP MANAGER task*/
    xTaskCreate(
        sleep_manager_task,
        "sleep_manager",
        4096,
        NULL,
        7,
        NULL
    );

    printf(
        "[MAIN] P4 system started\n"
    );
}