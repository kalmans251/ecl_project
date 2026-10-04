#include <Arduino.h>

#include "board_config.h"
#include "controller.h"
#include "ble_link.h"
#include "radar_manager.h"
#include "emergency_button.h"
#include "audio_session.h"

void setup()
{
    Serial.begin(
        115200
    );


    delay(
        1000
    );


    Serial.println();
    Serial.println(
        "========================================"
    );
    Serial.println(
        " ESP32-S3 START"
    );
    Serial.println(
        "========================================"
    );


    Serial.printf(
        "RAILING ID : %d\n",
        RAILING_ID
    );


    Serial.println(
        "Protocol   : SERVICE + CRC16"
    );


    Serial.println(
        "BLE RX     : StreamBuffer"
    );


    Serial.println(
        "BLE MTU    : 185"
    );


    Serial.println(
        "========================================"
    );


    // --------------------------------------------------------
    // Controller
    // --------------------------------------------------------

    controller_init();
    radar_manager_init();
    emergency_button_init();
    audio_session_init();

    // --------------------------------------------------------
    // BLE
    // --------------------------------------------------------

    ble_link_init();


    Serial.println();
    Serial.println(
        "[MAIN] S3 ready"
    );
}


void loop()
{
    /*
     * BLE callback이 받아놓은 데이터를
     * 여기서 실제 처리.
     */
    ble_link_process();

    radar_manager_process();
    
    emergency_button_process();

    /*
     * 다른 Arduino / FreeRTOS 작업에
     * CPU 시간 양보.
     *
     * 기존 delay(1000) 사용 금지.
     */
    delay(
        1
    );
}