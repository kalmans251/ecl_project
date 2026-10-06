#include "audio_output.h"

#include "board_config.h"

#include "driver/i2s_std.h"

#include "esp_err.h"
#include "esp_log.h"

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"


static portMUX_TYPE s_owner_lock = portMUX_INITIALIZER_UNLOCKED;
static TaskHandle_t s_owner;
static bool output_allowed(void)
{
    portENTER_CRITICAL(&s_owner_lock);
    bool allowed = !s_owner || s_owner == xTaskGetCurrentTaskHandle();
    portEXIT_CRITICAL(&s_owner_lock);
    return allowed;
}
bool audio_output_claim(void)
{
    portENTER_CRITICAL(&s_owner_lock);
    bool allowed = !s_owner || s_owner == xTaskGetCurrentTaskHandle();
    if (allowed) s_owner = xTaskGetCurrentTaskHandle();
    portEXIT_CRITICAL(&s_owner_lock);
    return allowed;
}
void audio_output_release(void)
{
    portENTER_CRITICAL(&s_owner_lock);
    if (s_owner == xTaskGetCurrentTaskHandle()) s_owner = NULL;
    portEXIT_CRITICAL(&s_owner_lock);
}

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

static bool s_voice_profile;


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

static bool init_profile(uint32_t sample_rate, bool voice)
{
    if (!output_allowed()) return false;

    if (
        sample_rate ==
        0
    )
    {
        return false;
    }


    if (s_initialized && s_voice_profile != voice) audio_output_deinit();

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


    /* Music PAUSE stops feeding PCM while I2S remains enabled. Clear each
     * completed TX buffer so DMA underrun emits silence, not stale music.
     * This also silences gaps between tracks without changing resume position.
     */
    chan_config.auto_clear_after_cb = true;
    if (voice) {
        /* 16kHz stereo PCM: 4 x 160 x 4 = 2560 bytes, 40ms of DMA audio.
         * Leave the normal music/emergency profile at the IDF defaults. */
        chan_config.dma_desc_num = 4;
        chan_config.dma_frame_num = 160;
    }

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
    s_voice_profile = voice;


    ESP_LOGI(
        TAG,
        "I2S %lu Hz BCLK=%d LRCK=%d DOUT=%d volume=%u%% dma=%lu x %lu",
        (unsigned long)sample_rate,
        I2S_BCLK_PIN,
        I2S_LRCK_PIN,
        I2S_DOUT_PIN,
        s_volume_percent,
        (unsigned long)chan_config.dma_desc_num,
        (unsigned long)chan_config.dma_frame_num
    );


    return true;
}


bool audio_output_init(uint32_t sample_rate)
{
    return init_profile(sample_rate, false);
}

bool audio_output_init_voice(void)
{
    return init_profile(16000, true);
}

/* ============================================================
 * SAMPLE RATE
 * ============================================================ */

bool audio_output_set_sample_rate(
    uint32_t sample_rate
)
{
    if (!output_allowed()) return false;

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
    if (!output_allowed()) return false;

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
    if (!output_allowed()) return;

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


uint32_t audio_output_get_sample_rate(void)
{
    return s_sample_rate;
}


/* ============================================================
 * DEINIT
 * ============================================================ */

void audio_output_deinit(void)
{
    if (!output_allowed()) return;

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