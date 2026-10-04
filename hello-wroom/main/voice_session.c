#include "voice_session.h"

#include "esp_log.h"


static const char *TAG =
    "VOICE_SESSION";


static bool
    s_active =
        false;


static audio_direction_t
    s_direction =
        AUDIO_DIR_FIELD_TX;


static uint32_t
    s_codec2_rx_packets =
        0;


static uint16_t
read_u16_be(
    const uint8_t *data
)
{
    return
        (
            ((uint16_t)data[0])
            <<
            8
        )
        |
        data[1];
}


void voice_session_init(void)
{
    s_active =
        false;

    s_direction =
        AUDIO_DIR_FIELD_TX;

    s_codec2_rx_packets =
        0;


    ESP_LOGI(
        TAG,
        "Voice session ready"
    );
}


void voice_session_start(void)
{
    s_active =
        true;

    s_direction =
        AUDIO_DIR_FIELD_TX;

    s_codec2_rx_packets =
        0;


    ESP_LOGI(
        TAG,
        "CALL START -> FIELD_TX"
    );
}


void voice_session_stop(void)
{
    s_active =
        false;

    s_direction =
        AUDIO_DIR_FIELD_TX;


    ESP_LOGI(
        TAG,
        "CALL STOP"
    );
}


bool voice_session_set_direction(
    audio_direction_t direction
)
{
    if (
        direction !=
        AUDIO_DIR_FIELD_TX
        &&
        direction !=
        AUDIO_DIR_CONTROL_TX
    )
    {
        return false;
    }


    s_direction =
        direction;


    ESP_LOGI(
        TAG,
        "DIRECTION -> %s",
        direction ==
            AUDIO_DIR_CONTROL_TX
            ?
            "CONTROL_TX"
            :
            "FIELD_TX"
    );


    return true;
}


bool voice_session_is_active(void)
{
    return s_active;
}


audio_direction_t
voice_session_get_direction(void)
{
    return s_direction;
}


bool voice_session_handle_codec2(
    const uint8_t *payload,
    size_t length
)
{
    if (
        payload ==
        NULL
        ||
        length <
        AUDIO_CODEC2_META_SIZE
    )
    {
        return false;
    }


    if (
        payload[0] !=
        AUDIO_DATA_CODEC2
    )
    {
        return false;
    }


    uint8_t mode =
        payload[1];


    uint8_t direction =
        payload[2];


    uint16_t sequence =
        read_u16_be(
            &payload[3]
        );


    uint8_t frame_count =
        payload[5];


    uint8_t bytes_per_frame =
        payload[6];


    if (
        mode !=
        CODEC2_MODE_2400
        ||
        direction !=
        AUDIO_DIR_CONTROL_TX
        ||
        !s_active
        ||
        s_direction !=
        AUDIO_DIR_CONTROL_TX
        ||
        frame_count ==
        0
        ||
        frame_count >
        CODEC2_MAX_FRAMES_PER_PACKET
        ||
        bytes_per_frame !=
        CODEC2_2400_BYTES_PER_FRAME
    )
    {
        ESP_LOGW(
            TAG,
            "Reject Codec2 active=%d session_dir=%u packet_dir=%u "
            "mode=%u frames=%u bpf=%u",
            s_active,
            (unsigned)s_direction,
            (unsigned)direction,
            (unsigned)mode,
            (unsigned)frame_count,
            (unsigned)bytes_per_frame
        );


        return false;
    }


    size_t expected =
        AUDIO_CODEC2_META_SIZE
        +
        (
            (size_t)frame_count
            *
            bytes_per_frame
        );


    if (
        length !=
        expected
    )
    {
        ESP_LOGW(
            TAG,
            "Reject Codec2 size=%u expected=%u",
            (unsigned)length,
            (unsigned)expected
        );


        return false;
    }


    s_codec2_rx_packets++;


    if (
        s_codec2_rx_packets ==
        1
        ||
        (
            s_codec2_rx_packets
            %
            25
        )
        ==
        0
    )
    {
        ESP_LOGI(
            TAG,
            "Codec2 RX seq=%u frames=%u bytes=%u packets=%lu",
            (unsigned)sequence,
            (unsigned)frame_count,
            (unsigned)(
                frame_count
                *
                bytes_per_frame
            ),
            (unsigned long)
                s_codec2_rx_packets
        );
    }


    /*
     * NEXT:
     * Feed payload[AUDIO_CODEC2_META_SIZE..] to the
     * WROOM Codec2 decoder / speaker pipeline.
     */


    return true;
}
