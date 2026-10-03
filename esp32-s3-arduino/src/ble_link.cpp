#include <Arduino.h>

#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>

#include "freertos/FreeRTOS.h"
#include "freertos/stream_buffer.h"

#include "board_config.h"
#include "protocol.h"
#include "protocol_parser.h"
#include "controller.h"
#include "ble_link.h"


// ============================================================
// BLE OBJECTS
// ============================================================

static BLEServer *ble_server =
    nullptr;

static BLEService *ble_service =
    nullptr;

static BLECharacteristic *rx_characteristic =
    nullptr;

static BLECharacteristic *tx_characteristic =
    nullptr;


// ============================================================
// CONNECTION STATE
// ============================================================

static volatile bool ble_connected =
    false;


// ============================================================
// RX STREAM BUFFER
//
// 중요:
//
// BLE callback에서는 Parser/Controller를 호출하지 않는다.
//
// 받은 바이트만 이 StreamBuffer에 넣고
// 즉시 callback을 종료한다.
// ============================================================

static StreamBufferHandle_t ble_rx_stream =
    nullptr;


static volatile uint32_t ble_rx_drop_count =
    0;


// ============================================================
// PROTOCOL PARSER
// ============================================================

static protocol_parser_t protocol_parser;


// ============================================================
// SERVER CALLBACK
// ============================================================

class ServerCallbacks :
    public BLEServerCallbacks
{
    void onConnect(
        BLEServer *server
    ) override
    {
        ble_connected =
            true;


        Serial.println();
        Serial.println(
            "[BLE] WROOM connected"
        );


        /*
         * 새로운 연결에서 Parser 상태 초기화
         */
        protocol_parser_reset(
            &protocol_parser
        );


        /*
         * 이전 연결에서 남아 있던 데이터 제거
         */
        if (
            ble_rx_stream !=
            nullptr
        )
        {
            xStreamBufferReset(
                ble_rx_stream
            );
        }
    }


    void onDisconnect(
        BLEServer *server
    ) override
    {
        ble_connected =
            false;


        Serial.println();
        Serial.println(
            "[BLE] WROOM disconnected"
        );


        protocol_parser_reset(
            &protocol_parser
        );


        if (
            ble_rx_stream !=
            nullptr
        )
        {
            xStreamBufferReset(
                ble_rx_stream
            );
        }


        /*
         * 다시 광고 시작
         */
        BLEDevice::startAdvertising();


        Serial.println(
            "[BLE] Advertising restarted"
        );
    }
};


// ============================================================
// RX CALLBACK
//
// WROOM -> S3
//
// 절대로 여기서:
//
// - Parser 처리
// - Controller 처리
// - notify()
// - delay()
//
// 하지 않는다.
// ============================================================

class RxCallbacks :
    public BLECharacteristicCallbacks
{
    void onWrite(
        BLECharacteristic *characteristic
    ) override
    {
        if (
            characteristic == nullptr ||
            ble_rx_stream == nullptr
        )
        {
            return;
        }


        /*
         * Arduino ESP32 BLE 버전에 따라
         * String 또는 std::string일 수 있으므로
         * auto 사용
         */
        auto value =
            characteristic->getValue();


        size_t len =
            value.length();


        if (len == 0)
        {
            return;
        }


        /*
         * 공간이 부족하면
         * 중간 일부만 넣지 않고
         * 이번 BLE packet 전체를 버린다.
         *
         * 중간 바이트가 잘리면
         * Protocol Parser가 틀어지기 때문.
         */
        size_t available =
            xStreamBufferSpacesAvailable(
                ble_rx_stream
            );


        if (available < len)
        {
            ble_rx_drop_count +=
                len;


            Serial.printf(
                "[BLE RX] DROP "
                "len=%u "
                "free=%u "
                "total_drop=%lu\n",

                (unsigned)len,
                (unsigned)available,
                (unsigned long)
                    ble_rx_drop_count
            );


            return;
        }


        size_t written =
            xStreamBufferSend(
                ble_rx_stream,
                (const uint8_t *)
                    value.c_str(),
                len,
                0
            );


        if (written != len)
        {
            ble_rx_drop_count +=
                (len - written);
        }


        /*
         * 여기에서 바로 return.
         *
         * 실제 Protocol 처리는
         * ble_link_process()에서 수행.
         */
    }
};


// ============================================================
// BLE INIT
// ============================================================

void ble_link_init(void)
{
    Serial.println(
        "[BLE] Initializing..."
    );


    // --------------------------------------------------------
    // Protocol Parser
    // --------------------------------------------------------

    protocol_parser_init(
        &protocol_parser
    );


    // --------------------------------------------------------
    // RX StreamBuffer
    // --------------------------------------------------------

    ble_rx_stream =
        xStreamBufferCreate(
            BLE_RX_STREAM_SIZE,
            1
        );


    if (
        ble_rx_stream ==
        nullptr
    )
    {
        Serial.println(
            "[BLE] RX StreamBuffer create FAILED"
        );

        return;
    }


    Serial.printf(
        "[BLE] RX StreamBuffer=%u bytes\n",
        BLE_RX_STREAM_SIZE
    );


    // --------------------------------------------------------
    // BLE Device
    // --------------------------------------------------------

    BLEDevice::init(
        BLE_DEVICE_NAME
    );


    BLEDevice::setMTU(
        BLE_PREFERRED_MTU
    );


    // --------------------------------------------------------
    // Server
    // --------------------------------------------------------

    ble_server =
        BLEDevice::createServer();


    ble_server->setCallbacks(
        new ServerCallbacks()
    );


    // --------------------------------------------------------
    // Service
    // --------------------------------------------------------

    ble_service =
        ble_server->createService(
            BLE_SERVICE_UUID
        );


    // --------------------------------------------------------
    // TX
    //
    // S3 -> WROOM
    // NOTIFY
    // --------------------------------------------------------

    tx_characteristic =
        ble_service->createCharacteristic(
            BLE_TX_CHAR_UUID,
            BLECharacteristic::PROPERTY_NOTIFY
        );


    /*
     * CCCD 0x2902
     *
     * WROOM이 Notify를 subscribe 할 수 있게 한다.
     */
    tx_characteristic->addDescriptor(
        new BLE2902()
    );


    // --------------------------------------------------------
    // RX
    //
    // WROOM -> S3
    //
    // WRITE + WRITE WITHOUT RESPONSE
    // --------------------------------------------------------

    rx_characteristic =
        ble_service->createCharacteristic(
            BLE_RX_CHAR_UUID,

            BLECharacteristic::PROPERTY_WRITE |
            BLECharacteristic::PROPERTY_WRITE_NR
        );


    rx_characteristic->setCallbacks(
        new RxCallbacks()
    );


    // --------------------------------------------------------
    // START SERVICE
    // --------------------------------------------------------

    ble_service->start();


    // --------------------------------------------------------
    // ADVERTISING
    // --------------------------------------------------------

    BLEAdvertising *advertising =
        BLEDevice::getAdvertising();


    advertising->addServiceUUID(
        BLE_SERVICE_UUID
    );


    advertising->setScanResponse(
        true
    );


    advertising->start();


    Serial.println(
        "[BLE] Advertising started"
    );


    Serial.printf(
        "[BLE] Preferred MTU=%d\n",
        BLE_PREFERRED_MTU
    );
}


// ============================================================
// CONNECTION STATUS
// ============================================================

bool ble_link_is_connected(void)
{
    return ble_connected;
}


// ============================================================
// BLE SEND
//
// S3 -> WROOM
//
// 중요:
//
// 이 함수는 이제 BLE onWrite callback 내부가 아니라
// loop() -> ble_link_process()
// -> controller_handle()
//
// 경로에서 실행된다.
// ============================================================

bool ble_send_frame(
    const protocol_frame_t *frame
)
{
    if (
        frame == nullptr
    )
    {
        return false;
    }


    if (
        !ble_connected ||
        tx_characteristic ==
        nullptr
    )
    {
        Serial.println(
            "[BLE TX] Not connected"
        );

        return false;
    }


    uint8_t buffer[
        PROTOCOL_MAX_FRAME_SIZE
    ];


    int length =
        protocol_encode(
            frame,
            buffer,
            sizeof(buffer)
        );


    if (length <= 0)
    {
        Serial.printf(
            "[BLE TX] Encode error=%d\n",
            length
        );

        return false;
    }


    /*
     * 현재는 MTU 185이므로
     * 최대 frame 138B를 그대로 전송한다.
     *
     * 이번 테스트에서 여전히 64/128B가 끊긴다면
     * 다음 단계에서 여기만 chunking 하면 된다.
     */

    tx_characteristic->setValue(
        buffer,
        length
    );


    tx_characteristic->notify();


    Serial.printf(
        "[BLE TX] "
        "RAIL=%02X "
        "SRC=%02X "
        "DST=%02X "
        "SERVICE=%02X "
        "CMD=%02X "
        "PAYLOAD=%u "
        "FRAME=%d\n",

        frame->railing_id,
        frame->src,
        frame->dst,
        frame->service,
        frame->command,
        frame->length,
        length
    );


    return true;
}


// ============================================================
// PROCESS
//
// loop()에서 계속 호출.
//
// BLE RX callback은 단순히 StreamBuffer에 넣고 끝냈고,
// 실제 Parser/Controller는 이 함수에서 실행된다.
// ============================================================

void ble_link_process(void)
{
    if (
        ble_rx_stream ==
        nullptr
    )
    {
        return;
    }


    uint8_t buffer[
        BLE_RX_PROCESS_SIZE
    ];


    /*
     * 현재 들어와 있는 데이터만 꺼냄.
     *
     * block하지 않는다.
     */
    size_t length =
        xStreamBufferReceive(
            ble_rx_stream,
            buffer,
            sizeof(buffer),
            0
        );


    if (length == 0)
    {
        return;
    }


    // --------------------------------------------------------
    // STREAM -> PROTOCOL PARSER
    // --------------------------------------------------------

    for (
        size_t i = 0;
        i < length;
        i++
    )
    {
        protocol_frame_t frame;


        bool complete =
            protocol_parser_input(
                &protocol_parser,
                buffer[i],
                &frame
            );


        if (!complete)
        {
            continue;
        }


        Serial.printf(
            "[PROTO RX] "
            "RAIL=%02X "
            "SRC=%02X "
            "DST=%02X "
            "SERVICE=%02X "
            "CMD=%02X "
            "LEN=%u\n",

            frame.railing_id,
            frame.src,
            frame.dst,
            frame.service,
            frame.command,
            frame.length
        );


        // ----------------------------------------------------
        // 여기서 Controller 실행
        //
        // 이제 BLE callback context가 아니다.
        // ----------------------------------------------------

        controller_handle(
            &frame
        );
    }
}