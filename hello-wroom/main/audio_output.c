#include "audio_output.h"

#include "board_config.h"

#include "driver/i2s_std.h"

#include "esp_err.h"
#include "esp_log.h"

#include "freertos/FreeRTOS.h"


#define AUDIO_MAX_SAMPLES \
    2304


static const char *TAG =
    "AUDIO_OUT";


static i2s_chan_handle_t
s_tx_handle =
    NULL;


static bool
s_initialized =
    false;


static uint32_t
s_sample_rate =
    0;


static uint8_t
s_volume_percent =
    20;


static int16_t
s_volume_buffer[
    AUDIO_MAX_SAMPLES
];


/* ============================================================
 * INIT
 * ============================================================ */

bool audio_output_init(
    uint32_t sample_rate
)
{
    if (
        sample_rate ==
        0
    )
    {
        return false;
    }


    if (
        s_initialized
    )
    {
        return audio_output_set_sample_rate(
            sample_rate
        );
    }


    i2s_chan_config_t chan_config =
        I2S_CHANNEL_DEFAULT_CONFIG(
            I2S_NUM_0,

            I2S_ROLE_MASTER
        );


    esp_err_t err =
        i2s_new_channel(
            &chan_config,

            &s_tx_handle,

            NULL
        );


    if (
        err !=
        ESP_OK
    )
    {
        return false;
    }


    i2s_std_config_t std_config =
    {
        .clk_cfg =
            I2S_STD_CLK_DEFAULT_CONFIG(
                sample_rate
            ),


        .slot_cfg =
            I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(
                I2S_DATA_BIT_WIDTH_16BIT,

                I2S_SLOT_MODE_STEREO
            ),


        .gpio_cfg =
        {
            .mclk =
                I2S_GPIO_UNUSED,

            .bclk =
                I2S_BCLK_PIN,

            .ws =
                I2S_LRCK_PIN,

            .dout =
                I2S_DOUT_PIN,

            .din =
                I2S_GPIO_UNUSED,


            .invert_flags =
            {
                .mclk_inv =
                    false,

                .bclk_inv =
                    false,

                .ws_inv =
                    false,
            },
        },
    };


    err =
        i2s_channel_init_std_mode(
            s_tx_handle,

            &std_config
        );


    if (
        err !=
        ESP_OK
    )
    {
        i2s_del_channel(
            s_tx_handle
        );


        s_tx_handle =
            NULL;


        return false;
    }


    err =
        i2s_channel_enable(
            s_tx_handle
        );


    if (
        err !=
        ESP_OK
    )
    {
        i2s_del_channel(
            s_tx_handle
        );


        s_tx_handle =
            NULL;


        return false;
    }


    s_sample_rate =
        sample_rate;


    s_initialized =
        true;


    ESP_LOGI(
        TAG,
        "I2S %lu Hz BCLK=%d LRCK=%d DOUT=%d volume=%u%%",
        (unsigned long)sample_rate,
        I2S_BCLK_PIN,
        I2S_LRCK_PIN,
        I2S_DOUT_PIN,
        s_volume_percent
    );


    return true;
}


/* ============================================================
 * SAMPLE RATE
 * ============================================================ */

bool audio_output_set_sample_rate(
    uint32_t sample_rate
)
{
    if (
        !s_initialized ||
        s_tx_handle == NULL
    )
    {
        return audio_output_init(
            sample_rate
        );
    }


    if (
        s_sample_rate ==
        sample_rate
    )
    {
        return true;
    }


    if (
        i2s_channel_disable(
            s_tx_handle
        )
        !=
        ESP_OK
    )
    {
        return false;
    }


    i2s_std_clk_config_t clk_config =
        I2S_STD_CLK_DEFAULT_CONFIG(
            sample_rate
        );


    if (
        i2s_channel_reconfig_std_clock(
            s_tx_handle,

            &clk_config
        )
        !=
        ESP_OK
    )
    {
        return false;
    }


    if (
        i2s_channel_enable(
            s_tx_handle
        )
        !=
        ESP_OK
    )
    {
        return false;
    }


    s_sample_rate =
        sample_rate;


    return true;
}


/* ============================================================
 * WRITE
 * ============================================================ */

bool audio_output_write(
    const int16_t *pcm,
    size_t sample_count
)
{
    if (
        !s_initialized ||
        s_tx_handle == NULL ||
        pcm == NULL ||
        sample_count == 0
    )
    {
        return false;
    }


    if (
        sample_count >
        AUDIO_MAX_SAMPLES
    )
    {
        return false;
    }


    for (
        size_t i = 0;
        i < sample_count;
        i++
    )
    {
        int32_t value =
            pcm[i];


        value =
            (
                value *
                s_volume_percent
            )
            /
            100;


        s_volume_buffer[i] =
            (int16_t)value;
    }


    size_t bytes_to_write =
        sample_count *
        sizeof(int16_t);


    size_t bytes_written =
        0;


    esp_err_t err =
        i2s_channel_write(
            s_tx_handle,

            s_volume_buffer,

            bytes_to_write,

            &bytes_written,

            portMAX_DELAY
        );


    return
        err ==
        ESP_OK
        &&
        bytes_written ==
        bytes_to_write;
}


/* ============================================================
 * VOLUME
 * ============================================================ */

void audio_output_set_volume(
    uint8_t volume_percent
)
{
    if (
        volume_percent >
        100
    )
    {
        volume_percent =
            100;
    }


    s_volume_percent =
        volume_percent;


    ESP_LOGI(
        TAG,
        "Volume=%u%%",
        s_volume_percent
    );
}


uint8_t audio_output_get_volume(void)
{
    return s_volume_percent;
}


/* ============================================================
 * DEINIT
 * ============================================================ */

void audio_output_deinit(void)
{
    if (
        s_tx_handle !=
        NULL
    )
    {
        if (
            s_initialized
        )
        {
            i2s_channel_disable(
                s_tx_handle
            );
        }


        i2s_del_channel(
            s_tx_handle
        );


        s_tx_handle =
            NULL;
    }


    s_initialized =
        false;


    s_sample_rate =
        0;


    ESP_LOGI(
        TAG,
        "I2S deinitialized"
    );
}


bool audio_output_is_initialized(void)
{
    return s_initialized;
}