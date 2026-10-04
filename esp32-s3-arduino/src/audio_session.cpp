#include <Arduino.h>

#include "protocol.h"
#include "audio_session.h"


static bool
    s_active =
        false;


static uint8_t
    s_direction =
        AUDIO_DIRECTION_FIELD_TX;


void audio_session_init(void)
{
    s_active =
        false;

    s_direction =
        AUDIO_DIRECTION_FIELD_TX;


    Serial.println(
        "[AUDIO] Session ready"
    );
}


void audio_session_start(void)
{
    s_active =
        true;

    s_direction =
        AUDIO_DIRECTION_FIELD_TX;


    Serial.println(
        "[AUDIO] CALL START -> FIELD_TX"
    );
}


void audio_session_stop(void)
{
    s_active =
        false;

    s_direction =
        AUDIO_DIRECTION_FIELD_TX;


    Serial.println(
        "[AUDIO] CALL STOP"
    );
}


bool audio_session_set_direction(
    uint8_t direction
)
{
    if (
        direction !=
        AUDIO_DIRECTION_FIELD_TX
        &&
        direction !=
        AUDIO_DIRECTION_CONTROL_TX
    )
    {
        return false;
    }


    s_direction =
        direction;


    Serial.printf(
        "[AUDIO] DIRECTION -> %s\n",
        direction ==
            AUDIO_DIRECTION_CONTROL_TX
            ?
            "CONTROL_TX"
            :
            "FIELD_TX"
    );


    return true;
}


bool audio_session_is_active(void)
{
    return s_active;
}


uint8_t audio_session_get_direction(void)
{
    return s_direction;
}


bool audio_session_field_tx_enabled(void)
{
    return
        s_active
        &&
        s_direction ==
            AUDIO_DIRECTION_FIELD_TX;
}
