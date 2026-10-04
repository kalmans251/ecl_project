#include <Arduino.h>
#include "audio_session.h"
#include <HardwareSerial.h>

#include "esp_system.h"

#include "board_config.h"
#include "protocol.h"
#include "ble_link.h"
#include "radar_manager.h"


// ============================================================
// CONFIG
// ============================================================

static constexpr uint8_t RADAR_FRAME_SIZE =
    30;

static constexpr uint8_t RADAR_TARGET_COUNT =
    3;

static constexpr uint8_t RADAR_TARGET_SIZE =
    8;


/*
 * 사람 수가 최소 2 frame 연속 유지되어야
 * 실제 변화로 인정.
 *
 * LD2450 약 10 Hz 기준 약 200 ms.
 */
static constexpr uint8_t COUNT_STABLE_FRAMES =
    2;


/*
 * 좌표 상세정보 전송 주기.
 *
 * 200 ms = 5 Hz
 */
static constexpr uint32_t DETAIL_INTERVAL_MS =
    200;


// ============================================================
// UART
// ============================================================

static HardwareSerial
    s_radar1_serial(
        1
    );


static HardwareSerial
    s_radar2_serial(
        2
    );


// ============================================================
// PARSER
// ============================================================

typedef struct
{
    uint8_t buffer[
        RADAR_FRAME_SIZE
    ];

    uint8_t index;

    uint8_t header_index;

    bool collecting;

} radar_parser_t;


static radar_parser_t
    s_parser1 = {};


static radar_parser_t
    s_parser2 = {};


// ============================================================
// RADAR STATE
// ============================================================

typedef struct
{
    radar_target_t targets[
        RADAR_TARGET_COUNT
    ];

    uint8_t target_count;


    /*
     * 신규 사람 판정을 위한 안정화 상태
     */
    uint8_t stable_count;

    uint8_t candidate_count;

    uint8_t candidate_frames;


    uint32_t last_frame_ms;

} radar_state_t;


static radar_state_t
    s_radar1 = {};


static radar_state_t
    s_radar2 = {};


// ============================================================
// GLOBAL STATE
// ============================================================

static bool
    s_detail_enabled =
        false;


static uint8_t
    s_position_source =
        RADAR_POSITION_SOURCE;


static uint32_t
    s_last_detail_ms =
        0;


static uint32_t
    s_detection_seq =
        1;


// ============================================================
// SIGN / MAGNITUDE DECODE
//
// LD2450:
//
// bit15 = 1 : positive
// bit15 = 0 : negative
//
// remaining 15bit = magnitude
// ============================================================

static int16_t decode_signed_value(
    uint8_t low,
    uint8_t high
)
{
    uint16_t raw =
        (uint16_t)low
        |
        (
            (uint16_t)high
            <<
            8
        );


    int16_t magnitude =
        (int16_t)(
            raw
            &
            0x7FFF
        );


    if (
        magnitude ==
        0
    )
    {
        return 0;
    }


    if (
        raw
        &
        0x8000
    )
    {
        return magnitude;
    }


    return
        -magnitude;
}


// ============================================================
// BIG ENDIAN WRITE
// ============================================================

static void write_u16_be(
    uint8_t *dst,
    uint16_t value
)
{
    dst[0] =
        (uint8_t)(
            value >> 8
        );

    dst[1] =
        (uint8_t)value;
}


static void write_i16_be(
    uint8_t *dst,
    int16_t value
)
{
    write_u16_be(
        dst,
        (uint16_t)value
    );
}


static void write_u32_be(
    uint8_t *dst,
    uint32_t value
)
{
    dst[0] =
        (uint8_t)(
            value >> 24
        );

    dst[1] =
        (uint8_t)(
            value >> 16
        );

    dst[2] =
        (uint8_t)(
            value >> 8
        );

    dst[3] =
        (uint8_t)value;
}


// ============================================================
// TARGET VALID
// ============================================================

static bool target_slot_valid(
    const uint8_t *data
)
{
    for (
        uint8_t i = 0;
        i < RADAR_TARGET_SIZE;
        i++
    )
    {
        if (
            data[i] !=
            0
        )
        {
            return true;
        }
    }


    return false;
}


// ============================================================
// PARSE TARGETS
// ============================================================

static void parse_targets(
    const uint8_t *frame,
    radar_state_t *state
)
{
    state->target_count =
        0;


    for (
        uint8_t target = 0;
        target < RADAR_TARGET_COUNT;
        target++
    )
    {
        const uint8_t *data =
            &frame[
                4 +
                (
                    target *
                    RADAR_TARGET_SIZE
                )
            ];


        radar_target_t *out =
            &state->targets[
                target
            ];


        bool valid =
            target_slot_valid(
                data
            );


        out->valid =
            valid;


        if (
            !valid
        )
        {
            out->x_mm =
                0;

            out->y_mm =
                0;

            out->speed_cms =
                0;

            out->resolution_mm =
                0;


            continue;
        }


        out->x_mm =
            decode_signed_value(
                data[0],
                data[1]
            );


        out->y_mm =
            decode_signed_value(
                data[2],
                data[3]
            );


        out->speed_cms =
            decode_signed_value(
                data[4],
                data[5]
            );


        out->resolution_mm =
            (uint16_t)data[6]
            |
            (
                (uint16_t)data[7]
                <<
                8
            );


        state->target_count++;
    }


    state->last_frame_ms =
        millis();
}


// ============================================================
// SEND NEW PERSON
//
// S3 -> P4
//
// SERVICE_DETECTION
// CMD_DATA
//
// [0]    DETECT_EVENT_RADAR_NEW_PERSON
// [1..4] seq
// ============================================================

static void send_new_person(
    uint8_t radar_id
)
{
    if (audio_session_is_active()) return;
    protocol_frame_t frame =
        {};


    frame.railing_id =
        RAILING_ID;

    frame.src =
        NODE_S3;

    frame.dst =
        NODE_P4;

    frame.service =
        SERVICE_DETECTION;

    frame.command =
        CMD_DATA;

    frame.length =
        5;


    frame.payload[0] =
        DETECT_EVENT_RADAR_NEW_PERSON;


    write_u32_be(
        &frame.payload[1],
        s_detection_seq
    );


    Serial.printf(
        "[RADAR%d] NEW PERSON seq=%lu\n",
        radar_id,
        (unsigned long)
            s_detection_seq
    );


    ble_send_frame(
        &frame
    );


    s_detection_seq++;


    if (
        s_detection_seq ==
        0
    )
    {
        s_detection_seq =
            1;
    }
}


// ============================================================
// COUNT FILTER
// ============================================================

static void update_detection_count(
    uint8_t radar_id,
    radar_state_t *state
)
{
    uint8_t current =
        state->target_count;


    if (
        current !=
        state->candidate_count
    )
    {
        state->candidate_count =
            current;

        state->candidate_frames =
            1;


        return;
    }


    if (
        state->candidate_frames <
        COUNT_STABLE_FRAMES
    )
    {
        state->candidate_frames++;
    }


    if (
        state->candidate_frames <
        COUNT_STABLE_FRAMES
    )
    {
        return;
    }


    if (
        state->stable_count ==
        current
    )
    {
        return;
    }


    uint8_t previous =
        state->stable_count;


    state->stable_count =
        current;


    /*
     * 증가한 경우만 신규 사람으로 판단.
     *
     * 감소는 사람이 빠져나간 것으로 보고
     * NEW_PERSON을 발생시키지 않는다.
     */
    if (
        current >
        previous
    )
    {
        uint8_t added =
            current -
            previous;


        for (
            uint8_t i = 0;
            i < added;
            i++
        )
        {
            send_new_person(
                radar_id
            );
        }
    }
}


// ============================================================
// SEND DETAIL
//
// 선택된 Radar 하나만.
//
// S3 -> PI
//
// payload:
//
// [0]     RADAR_DATA_TARGETS
// [1]     radar_id
// [2]     target_count
//
// 각 Target 8 byte:
//
// X          int16 BE
// Y          int16 BE
// speed      int16 BE
// resolution uint16 BE
//
// 총 27 bytes.
// ============================================================

static void send_radar_detail(
    uint8_t radar_id,
    const radar_state_t *state
)
{
    if (audio_session_is_active()) return;
    if (
        !s_detail_enabled
    )
    {
        return;
    }


    if (
        radar_id !=
        s_position_source
    )
    {
        return;
    }


    uint32_t now =
        millis();


    if (
        now -
        s_last_detail_ms
        <
        DETAIL_INTERVAL_MS
    )
    {
        return;
    }


    s_last_detail_ms =
        now;


    protocol_frame_t frame =
        {};


    frame.railing_id =
        RAILING_ID;

    frame.src =
        NODE_S3;

    /*
     * P4에서는 로컬 wake 판단을 하지 않고
     * 상세 좌표는 Pi가 받는다.
     */
    frame.dst =
        NODE_PI;

    frame.service =
        SERVICE_RADAR;

    frame.command =
        CMD_DATA;

    frame.length =
        27;


    frame.payload[0] =
        RADAR_DATA_TARGETS;

    frame.payload[1] =
        radar_id;

    frame.payload[2] =
        state->target_count;


    uint8_t offset =
        3;


    for (
        uint8_t i = 0;
        i < RADAR_TARGET_COUNT;
        i++
    )
    {
        const radar_target_t *target =
            &state->targets[i];


        if (
            target->valid
        )
        {
            write_i16_be(
                &frame.payload[offset],
                target->x_mm
            );

            write_i16_be(
                &frame.payload[offset + 2],
                target->y_mm
            );

            write_i16_be(
                &frame.payload[offset + 4],
                target->speed_cms
            );

            write_u16_be(
                &frame.payload[offset + 6],
                target->resolution_mm
            );
        }
        else
        {
            memset(
                &frame.payload[offset],
                0,
                8
            );
        }


        offset +=
            8;
    }


    ble_send_frame(
        &frame
    );
}


// ============================================================
// COMPLETE FRAME
// ============================================================

static void process_complete_frame(
    uint8_t radar_id,
    const uint8_t *frame
)
{
    radar_state_t *state =
        (
            radar_id ==
            1
        )
        ?
        &s_radar1
        :
        &s_radar2;


    parse_targets(
        frame,
        state
    );


    update_detection_count(
        radar_id,
        state
    );


    send_radar_detail(
        radar_id,
        state
    );
}


// ============================================================
// PARSER INPUT
// ============================================================

static void parser_input(
    radar_parser_t *parser,
    uint8_t radar_id,
    uint8_t value
)
{
    static const uint8_t header[4] =
    {
        0xAA,
        0xFF,
        0x03,
        0x00
    };


    /*
     * 아직 header 탐색 중
     */
    if (
        !parser->collecting
    )
    {
        if (
            value ==
            header[
                parser->header_index
            ]
        )
        {
            parser->header_index++;


            if (
                parser->header_index ==
                4
            )
            {
                memcpy(
                    parser->buffer,
                    header,
                    sizeof(header)
                );


                parser->index =
                    4;

                parser->header_index =
                    0;

                parser->collecting =
                    true;
            }
        }
        else
        {
            parser->header_index =
                (
                    value ==
                    0xAA
                )
                ?
                1
                :
                0;
        }


        return;
    }


    parser->buffer[
        parser->index++
    ] =
        value;


    if (
        parser->index <
        RADAR_FRAME_SIZE
    )
    {
        return;
    }


    /*
     * Footer 검사
     */
    bool valid =
        (
            parser->buffer[28]
            ==
            0x55
        )
        &&
        (
            parser->buffer[29]
            ==
            0xCC
        );


    if (
        valid
    )
    {
        process_complete_frame(
            radar_id,
            parser->buffer
        );
    }
    else
    {
        Serial.printf(
            "[RADAR%d] Invalid frame\n",
            radar_id
        );
    }


    parser->index =
        0;

    parser->header_index =
        0;

    parser->collecting =
        false;
}


// ============================================================
// PROCESS UART
// ============================================================

static void process_uart(
    HardwareSerial &serial,
    radar_parser_t *parser,
    uint8_t radar_id
)
{
    while (
        serial.available()
        >
        0
    )
    {
        int value =
            serial.read();


        if (
            value <
            0
        )
        {
            break;
        }


        parser_input(
            parser,
            radar_id,
            (uint8_t)value
        );
    }
}


// ============================================================
// INIT
// ============================================================

void radar_manager_init(void)
{
    memset(
        &s_parser1,
        0,
        sizeof(s_parser1)
    );

    memset(
        &s_parser2,
        0,
        sizeof(s_parser2)
    );


    memset(
        &s_radar1,
        0,
        sizeof(s_radar1)
    );

    memset(
        &s_radar2,
        0,
        sizeof(s_radar2)
    );


    s_detection_seq =
        esp_random();


    if (
        s_detection_seq ==
        0
    )
    {
        s_detection_seq =
            1;
    }


    s_position_source =
        RADAR_POSITION_SOURCE;


    s_radar1_serial.begin(
        LD2450_BAUDRATE,
        SERIAL_8N1,
        RADAR1_RX_IO,
        RADAR1_TX_IO
    );


    s_radar2_serial.begin(
        LD2450_BAUDRATE,
        SERIAL_8N1,
        RADAR2_RX_IO,
        RADAR2_TX_IO
    );


    Serial.printf(
        "[RADAR] RADAR1 RX=%d TX=%d\n",
        RADAR1_RX_IO,
        RADAR1_TX_IO
    );


    Serial.printf(
        "[RADAR] RADAR2 RX=%d TX=%d\n",
        RADAR2_RX_IO,
        RADAR2_TX_IO
    );


    Serial.printf(
        "[RADAR] baud=%lu position_source=%u\n",
        (unsigned long)
            LD2450_BAUDRATE,
        s_position_source
    );
}


// ============================================================
// PROCESS
// ============================================================

void radar_manager_process(void)
{
    process_uart(
        s_radar1_serial,
        &s_parser1,
        1
    );


    process_uart(
        s_radar2_serial,
        &s_parser2,
        2
    );
}


// ============================================================
// DETAIL
// ============================================================

void radar_manager_set_detail_enabled(
    bool enabled
)
{
    s_detail_enabled =
        enabled;


    Serial.printf(
        "[RADAR] detail=%s\n",
        enabled
            ?
            "ON"
            :
            "OFF"
    );
}


bool radar_manager_is_detail_enabled(void)
{
    return
        s_detail_enabled;
}


// ============================================================
// POSITION SOURCE
// ============================================================

bool radar_manager_set_position_source(
    uint8_t radar_id
)
{
    if (
        radar_id != 1
        &&
        radar_id != 2
    )
    {
        return false;
    }


    s_position_source =
        radar_id;


    Serial.printf(
        "[RADAR] position source=%u\n",
        radar_id
    );


    return true;
}


uint8_t radar_manager_get_position_source(void)
{
    return
        s_position_source;
}


// ============================================================
// TARGET COUNT
// ============================================================

uint8_t radar_manager_get_target_count(
    uint8_t radar_id
)
{
    if (
        radar_id ==
        1
    )
    {
        return
            s_radar1.target_count;
    }


    if (
        radar_id ==
        2
    )
    {
        return
            s_radar2.target_count;
    }


    return 0;
}
