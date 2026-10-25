#include <string.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "board_config.h"

#include "protocol.h"

#include "p4_controller.h"

#include "system_state.h"

#include "power_control.h"

#include "esp_log.h"

#include "router.h"

#include "led_task.h"
#include "led_eq_fresh.h"
#include "projector_control.h"

#include "detection_manager.h"

#include "sleep_manager.h"

#include "call_manager.h"
#include "music_policy.h"
#include "control_confirm.h"

#include "music_manager.h"
#include "emergency_manager.h"

/* ============================================================
 * LOG TAG
 * ============================================================ */

static const protocol_frame_t *s_apply_request;
static bool s_apply_accepted;
static BaseType_t enqueue_led(led_command_t *cmd) {
    if(s_apply_request) {
        cmd->confirm=true;cmd->reply_rail=s_apply_request->railing_id;
        cmd->reply_op=s_apply_request->payload[4];
        memcpy(cmd->request_id,s_apply_request->payload,4);
    }
    BaseType_t result=xQueueSend(led_command_queue,cmd,0);
    if(result==pdTRUE)s_apply_accepted=true;
    return result;
}

static const char *TAG = "P4_CONTROLLER";


/* ============================================================
 * PRIVATE FUNCTION PROTOTYPES
 * ============================================================ */

static void handle_power(
    const protocol_frame_t *frame
);

static void handle_projector(
    const protocol_frame_t *frame
);

static void handle_detection(
    const protocol_frame_t *frame
);

static void handle_music(
    const protocol_frame_t *frame
);

static void handle_sleep(
    const protocol_frame_t *frame
);

static void handle_audio(
    const protocol_frame_t *frame
);

static uint32_t read_u32_be(
    const uint8_t *data
)
{
    return
        ((uint32_t)data[0] << 24)
        |
        ((uint32_t)data[1] << 16)
        |
        ((uint32_t)data[2] << 8)
        |
        ((uint32_t)data[3]);
}

static void handle_emergency(
    const protocol_frame_t *frame
);
/* ============================================================
 * PLC TURNAROUND TEST
 *
 * Pi -> P4 요청을 완전히 받은 뒤
 * P4 -> Pi 응답을 보내기 전에 기다리는 시간.
 *
 * 테스트:
 * 0 / 10 / 20 / 50 ms
 * ============================================================ */

#define PLC_ECHO_TURNAROUND_DELAY_MS    0


/* ============================================================
 * RESPONSE
 * ============================================================ */

static void send_response(
    const protocol_frame_t *request,
    uint8_t service,
    uint8_t command,
    const uint8_t *payload,
    uint8_t length
)
{
    protocol_frame_t response = {0};


    response.railing_id =
        RAILING_ID;

    response.src =
        NODE_P4;

    response.dst =
        request->src;

    response.service =
        service;

    response.command =
        command;

    response.length =
        length;


    if (
        payload != NULL &&
        length > 0
    )
    {
        memcpy(
            response.payload,
            payload,
            length
        );
    }


    xQueueSend(
        router_queue,
        &response,
        portMAX_DELAY
    );
}


/* ============================================================
 * SYSTEM SERVICE
 * ============================================================ */

static void handle_system(
    const protocol_frame_t *frame
)
{
    switch (frame->command)
    {
        /* ----------------------------------------------------
         * PING
         * ---------------------------------------------------- */

        case CMD_PING:
        {
            send_response(
                frame,
                SERVICE_SYSTEM,
                CMD_PONG,
                NULL,
                0
            );

            break;
        }


        /* ----------------------------------------------------
         * ECHO
         *
         * PLC turnaround timing test
         * ---------------------------------------------------- */

        case CMD_ECHO:
        {
            /*
             * Pi -> P4 전송이 끝난 뒤
             * PLCMODEM2가 송신/수신 방향을 전환할
             * 시간을 주기 위한 테스트용 delay.
             *
             * 중요:
             * ECHO에만 적용.
             */
            if (
                PLC_ECHO_TURNAROUND_DELAY_MS > 0
            )
            {
                vTaskDelay(
                    pdMS_TO_TICKS(
                        PLC_ECHO_TURNAROUND_DELAY_MS
                    )
                );
            }


            send_response(
                frame,
                SERVICE_SYSTEM,
                CMD_ECHO_RESPONSE,
                frame->payload,
                frame->length
            );


            break;
        }


        /* ----------------------------------------------------
         * STATUS
         * ---------------------------------------------------- */

        case CMD_STATUS_REQUEST:
        {
            uint8_t status = 1;


            send_response(
                frame,
                SERVICE_SYSTEM,
                CMD_STATUS_RESPONSE,
                &status,
                1
            );


            break;
        }


        default:
        {
            break;
        }
    }
}


/* ============================================================
 * LED SERVICE
 *
 * 실제 LED Task는 다음 단계에서 연결.
 * ============================================================ */

static void handle_led(
    const protocol_frame_t *frame
)
{
    switch (frame->command)
    {
        /* ====================================================
         * START
         * ==================================================== */

        case CMD_START:
        {
            led_command_t cmd =
            {
                .type =
                    LED_COMMAND_START
            };


            enqueue_led(&cmd);


            break;
        }


        /* ====================================================
         * STOP
         * ==================================================== */

        case CMD_STOP:
        {
            led_command_t cmd =
            {
                .type =
                    LED_COMMAND_STOP
            };


            enqueue_led(&cmd);


            break;
        }


        /* ====================================================
         * SET
         *
         * payload:
         *
         * [0] LED MODE
         *
         * 01 BASIC
         * 02 WEATHER
         * 03 MUSIC
         *
         * WEATHER일 경우
         *
         * [1] WEATHER TYPE
         * ==================================================== */

        case CMD_SET:
        {
            if (
                frame->length <
                1
            )
            {
                break;
            }


            uint8_t mode =
                frame->payload[0];


            if (
                mode <
                LED_MODE_BASIC ||
                mode >
                LED_MODE_MUSIC
            )
            {
                break;
            }
            p4_system_state_t previous_state;


            system_state_get(
                &previous_state
            );


            /* Backward compatible SET: [mode] retains the selected pattern;
             * BASIC/MUSIC may add a zero-based pattern in byte 1.
             * WEATHER byte 1 keeps its existing weather meaning. */
            if (frame->length > 2 ||
                (frame->length == 2 &&
                 ((mode == LED_MODE_BASIC && frame->payload[1] >= 6) ||
                  (mode == LED_MODE_MUSIC && frame->payload[1] >= 3) ||
                  (mode == LED_MODE_WEATHER && frame->payload[1] > WEATHER_SNOW)))) {
                break;
            }
            uint8_t pattern = mode == LED_MODE_MUSIC
                ? previous_state.led_music_pattern : previous_state.led_basic_pattern;
            if (mode != LED_MODE_WEATHER && frame->length == 2) pattern=frame->payload[1];

            led_mode_t old_mode =
                previous_state.led_mode;


            led_mode_t new_mode =
                (led_mode_t)
                mode;

            led_command_t cmd =
            {
                .type =
                    LED_COMMAND_SET_MODE,

                .pattern = pattern,
                .weather = (mode == LED_MODE_WEATHER && frame->length == 2)
                    ? (weather_type_t)frame->payload[1] : previous_state.weather_type,

                .mode =
                    (led_mode_t)
                    mode
            };


            if (enqueue_led(&cmd) != pdTRUE) break;
            system_state_set_led_pattern(new_mode,pattern);
            /*
            * System State에도 즉시 반영.
            *
            * led_task에서도 다시 같은 값을 넣지만
            * Sleep Manager가 mode 변경을 즉시 알 수 있도록 한다.
            */
            system_state_set_led_mode(
                new_mode
            );


            /* ========================================================
            * MUSIC -> BASIC / WEATHER
            * ======================================================== */

            if (
                old_mode ==
                    LED_MODE_MUSIC
                &&
                new_mode !=
                    LED_MODE_MUSIC
            )
            {
                ESP_LOGI(
                    TAG,
                    "LED MUSIC -> NON-MUSIC"
                );


                music_policy_add_pause_reason(
                    MUSIC_PAUSE_REASON_LED
                );


                /*
                * SLEEP_PENDING 상태라면
                * 곡 FINISHED를 더 이상 기다리지 않는다.
                */
                sleep_manager_on_led_mode_changed(
                    new_mode
                );
            }


            /* ========================================================
            * BASIC / WEATHER -> MUSIC
            * ======================================================== */

            else if (
                old_mode !=
                    LED_MODE_MUSIC
                &&
                new_mode ==
                    LED_MODE_MUSIC
            )
            {
                music_policy_remove_pause_reason(
                    MUSIC_PAUSE_REASON_LED
                );


                music_manager_on_led_mode_changed(
                    new_mode
                );
            }

            if (new_mode == LED_MODE_WEATHER) system_state_set_weather(cmd.weather);

            break;
        }


        /* ====================================================
         * DATA
         *
         * MUSIC MODE EQ
         *
         * WROOM → P4
         * ==================================================== */

        case CMD_DATA:
        {
            /*
             * EQ는 WROOM에서 오는 것만 허용
             */
            if (
                frame->src !=
                NODE_WROOM
            )
            {
                break;
            }


            if (frame->length != LED_EQ_BANDS || call_manager_is_active())
            {
                break;
            }


            led_eq_data_t eq =
            {
                0
            };


            eq.length =
                frame->length;


            if (
                eq.length >
                LED_EQ_MAX_DATA
            )
            {
                eq.length =
                    LED_EQ_MAX_DATA;
            }


            memcpy(
                eq.data,
                frame->payload,
                eq.length
            );


            /*
             * 과거 EQ는 필요 없음.
             * 항상 최신값으로 교체.
             */
            xQueueOverwrite(
                led_eq_queue,
                &eq
            );


            break;
        }


        default:
        {
            break;
        }
    }
}

/* ============================================================
 * CONTROLLER TASK
 * ============================================================ */

/* APPLY v1: request_id[4], original command, original payload.
 * RESULT: request_id[4], original command, status, detail/status bytes.
 * 0=local execution complete, 1=rejected, 2=failed, 3=music policy only.
 * No automatic replay: NEXT/CCTV are not idempotent. */
static void handle_general_apply(const protocol_frame_t *request)
{
    static bool reset_cached=false;
    static uint8_t reset_rail,reset_token[4],reset_detail[6];
    if(request->length<5)return;
    protocol_frame_t f=*request;
    f.command=request->payload[4];f.length=request->length-5;
    memmove(f.payload,request->payload+5,f.length);
    uint8_t response[12]={0};memcpy(response,request->payload,5);
    uint8_t response_length=7;
    response[5]=1;
    bool active=call_manager_is_active() || emergency_manager_is_active();
    s_apply_accepted=false;
    if(!active) {
        p4_system_state_t state;system_state_get(&state);
        switch(f.service) {
        case SERVICE_SYSTEM:
            if(f.length==0 && (f.command==CMD_PING || f.command==CMD_STATUS_REQUEST)) {
                response[5]=0;response[6]=1;
            }
            break;
        case SERVICE_LED:
            if((f.length==0 && (f.command==CMD_START || f.command==CMD_STOP)) ||
               (f.command==CMD_SET && f.length>=1 && f.length<=2)) {
                s_apply_request=request;handle_led(&f);s_apply_request=NULL;
                if(s_apply_accepted)return; /* task sends completion */
                response[5]=2;
            }
            break;
        case SERVICE_POWER:
            if(f.command==CMD_SET && f.length==1 && (f.payload[0]==1 || f.payload[0]==2)) {
                handle_power(&f);system_state_get(&state);
                response[5]=state.power_mode==f.payload[0]?0:2;
            } else if(f.length==0 && (f.command==CMD_START || f.command==CMD_STOP) &&
                      (state.power_mode==POWER_MODE_AC || state.power_mode==POWER_MODE_BATTERY)) {
                handle_power(&f);
                bool enabled=state.power_mode==POWER_MODE_AC?power_control_get_ac():power_control_get_battery();
                response[5]=enabled==(f.command==CMD_START)?0:2;
            }
            break;
        case SERVICE_PROJECTOR:
            if(f.length==0 && (f.command==CMD_START || f.command==CMD_STOP)) {
                handle_projector(&f);response[5]=projector_control_get()==(f.command==CMD_START)?0:2;
            }
            break;
        case SERVICE_SLEEP:
            if(f.length==0 && (f.command==CMD_START || f.command==CMD_STOP)) {
                handle_sleep(&f);system_state_get(&state);
                response[5]=state.sleep_mode_enabled==(f.command==CMD_START)?0:2;
            }
            break;
        case SERVICE_DETECTION:
            if(f.length==0 && (f.command==CMD_STATUS_REQUEST || f.command==CMD_DETECTION_RESET)) {
                if(f.command==CMD_DETECTION_RESET && reset_cached && reset_rail==request->railing_id && !memcmp(reset_token,request->payload,4)) {
                    response[5]=0;memcpy(response+6,reset_detail,6);response_length=12;
                    break; /* Repeated transaction must not erase later detections. */
                }
                detection_summary_t summary;
                if(f.command==CMD_DETECTION_RESET)detection_manager_reset_count(&summary);
                else detection_manager_get_summary(&summary);
                uint32_t count=summary.total_detected_count;
                response[5]=0;response[6]=1;response[7]=(uint8_t)summary.source;
                response[8]=(uint8_t)(count>>24);response[9]=(uint8_t)(count>>16);
                response[10]=(uint8_t)(count>>8);response[11]=(uint8_t)count;
                response_length=12;
                if(f.command==CMD_DETECTION_RESET) {
                    reset_cached=true;reset_rail=request->railing_id;
                    memcpy(reset_token,request->payload,4);memcpy(reset_detail,response+6,6);
                }
            } else if(f.command==CMD_SET && f.length==1 && f.payload[0]<=1) {
                handle_detection(&f);response[5]=detection_manager_get_source()==f.payload[0]?0:2;
            } else if(f.command==CMD_DATA &&
                ((f.length==5 && f.payload[0]==DETECT_EVENT_CCTV_NEW_PERSON) ||
                 (f.length==6 && f.payload[0]==DETECT_EVENT_CCTV_AGE_RESULT &&
                  ((f.payload[5]>=1 && f.payload[5]<=4) || f.payload[5]==255)))) {
                handle_detection(&f);response[5]=s_apply_accepted?0:1;
            }
            break;
        case SERVICE_MUSIC:
            control_confirm_begin(request);
            /* Existing policy may arm/reserve playback rather than start it.
             * Never label a manager return as WROOM execution confirmation. */
            if(f.length==0) {
                if(f.command==CMD_START)response[5]=music_manager_start()?3:2;
                else if(f.command==CMD_NEXT)response[5]=music_manager_next()?3:1;
                else if(f.command==CMD_PAUSE) {
                    music_manager_user_pause();response[5]=3;
                } else if(f.command==CMD_RESUME) {
                    music_manager_user_resume();response[5]=3;
                }
            } else if(f.command==CMD_SET && f.length==2 && f.payload[0]==MUSIC_SET_PLAY_MODE) {
                response[5]=music_manager_set_mode((music_play_mode_t)f.payload[1])?3:1;
            }
            if(control_confirm_end())return; /* WROOM task owns final result */
            break;
        default:break;
        }
    }
    send_response(request,request->service,CMD_APPLY_RESULT,response,response_length);
}

void p4_controller_task(
    void *arg
)
{
    protocol_frame_t frame;


    while (1)
    {
        call_manager_tick();
        if (
            xQueueReceive(
                p4_controller_queue,
                &frame,
                pdMS_TO_TICKS(100)
            ) != pdTRUE
        )
        {
            continue;
        }


        if(frame.src==NODE_PI && frame.command==CMD_APPLY) {
            bool wroom_apply=frame.service==SERVICE_MUSIC && frame.length>=5 &&
                (frame.payload[4]==CMD_MUSIC_INFO || frame.payload[4]==CMD_MUSIC_TIMELINE || frame.payload[4]==CMD_MUSIC_SEEK || frame.payload[4]==CMD_MUSIC_CATALOG ||
                 frame.payload[4]==CMD_MUSIC_TRACK || frame.payload[4]==CMD_MUSIC_PLAY || frame.payload[4]==CMD_STOP || (frame.payload[4]==CMD_SET &&
                 frame.length>=6 && frame.payload[5]==MUSIC_SET_VOLUME));
            if(wroom_apply)handle_music(&frame);
            else handle_general_apply(&frame);
            continue;
        }

        /* Pi general controls must not reconfigure hardware during a call. */
        if (frame.src == NODE_PI && call_manager_is_active()
                && frame.service != SERVICE_AUDIO && frame.service != SERVICE_EMERGENCY) {
            ESP_LOGW(TAG, "General Pi command blocked during call service=%u", frame.service);
            continue;
        }

        switch (frame.service)
        {
            case SERVICE_SYSTEM:
            {
                handle_system(
                    &frame
                );

                break;
            }


            case SERVICE_LED:
            {
                handle_led(
                    &frame
                );

                break;
            }


            case SERVICE_POWER:
            {
                handle_power(
                    &frame
                );

                break;
            }


            case SERVICE_PROJECTOR:
            {
                handle_projector(
                    &frame
                );

                break;
            }


            case SERVICE_DETECTION:
            {
                handle_detection(
                    &frame
                );

                break;
            }


            case SERVICE_MUSIC:
            {
                handle_music(
                    &frame
                );

                break;
            }


            case SERVICE_SLEEP:
            {
                handle_sleep(
                    &frame
                );

                break;
            }


            case SERVICE_AUDIO:
            {
                handle_audio(
                    &frame
                );

                break;
            }

            case SERVICE_EMERGENCY:
            {
                handle_emergency(
                    &frame
                );

                break;
            }
            
            default:
            {
                break;
            }
        }
    }
}


/* ============================================================
 * POWER TASK
 * ============================================================ */

static void handle_power(
    const protocol_frame_t *frame
)
{
    switch (
        frame->command
    )
    {
        /* ====================================================
         * SET
         *
         * payload[0]
         *
         * 00 AUTO
         * 01 AC
         * 02 BATTERY
         * ==================================================== */

        case CMD_SET:
        {
            if (
                frame->length <
                1
            )
            {
                ESP_LOGW(
                    TAG,
                    "POWER SET: no payload"
                );

                break;
            }


            uint8_t mode =
                frame->payload[0];


            switch (mode)
            {
                case POWER_MODE_AUTO:
                {
                    system_state_set_power_mode(
                        POWER_MODE_AUTO
                    );


                    ESP_LOGI(
                        TAG,
                        "POWER MODE = AUTO"
                    );


                    /*
                     * AUTO는 아직 실제 제어 미구현
                     */

                    break;
                }


                case POWER_MODE_AC:
                {
                    system_state_set_power_mode(
                        POWER_MODE_AC
                    );


                    ESP_LOGI(
                        TAG,
                        "POWER MODE = AC"
                    );


                    break;
                }


                case POWER_MODE_BATTERY:
                {
                    system_state_set_power_mode(
                        POWER_MODE_BATTERY
                    );


                    ESP_LOGI(
                        TAG,
                        "POWER MODE = BATTERY"
                    );


                    break;
                }


                default:
                {
                    ESP_LOGW(
                        TAG,
                        "Unknown POWER MODE=0x%02X",
                        mode
                    );


                    break;
                }
            }


            break;
        }


        /* ====================================================
         * START
         *
         * 현재 설정된 전원 모드를 실제 적용
         * ==================================================== */

        case CMD_START:
        {
            p4_system_state_t state;


            system_state_get(
                &state
            );


            switch (
                state.power_mode
            )
            {
                case POWER_MODE_AC:
                {
                    power_control_select_ac();


                    system_state_set_power_source(
                        POWER_SOURCE_AC
                    );


                    ESP_LOGI(
                        TAG,
                        "POWER START -> AC"
                    );


                    break;
                }


                case POWER_MODE_BATTERY:
                {
                    power_control_select_battery();


                    system_state_set_power_source(
                        POWER_SOURCE_BATTERY
                    );


                    ESP_LOGI(
                        TAG,
                        "POWER START -> BATTERY"
                    );


                    break;
                }


                case POWER_MODE_AUTO:
                {
                    ESP_LOGW(
                        TAG,
                        "AUTO control not implemented yet"
                    );


                    break;
                }


                default:
                {
                    break;
                }
            }


            break;
        }


        /* ====================================================
         * STOP
         *
         * 현재 테스트용
         *
         * 선택된 전원만 차단
         * ==================================================== */

        case CMD_STOP:
        {
            p4_system_state_t state;


            system_state_get(
                &state
            );


            switch (
                state.power_mode
            )
            {
                case POWER_MODE_AC:
                {
                    power_control_set_ac(
                        false
                    );


                    ESP_LOGI(
                        TAG,
                        "AC TEST STOP"
                    );


                    break;
                }


                case POWER_MODE_BATTERY:
                {
                    power_control_set_battery(
                        false
                    );


                    ESP_LOGI(
                        TAG,
                        "BATTERY TEST STOP"
                    );


                    break;
                }


                case POWER_MODE_AUTO:
                default:
                {
                    break;
                }
            }


            break;
        }


        default:
        {
            break;
        }
    }
}

static void handle_projector(
    const protocol_frame_t *frame
)
{
    switch (
        frame->command
    )
    {
        /* ====================================================
         * PROJECTOR ON
         * ==================================================== */

        case CMD_START:
        {
            system_state_set_projector_enabled(
                true
            );


            projector_control_set(
                true
            );


            ESP_LOGI(
                TAG,
                "PROJECTOR START"
            );


            break;
        }


        /* ====================================================
         * PROJECTOR OFF
         * ==================================================== */

        case CMD_STOP:
        {
            system_state_set_projector_enabled(
                false
            );


            projector_control_set(
                false
            );


            ESP_LOGI(
                TAG,
                "PROJECTOR STOP"
            );


            break;
        }


        default:
        {
            break;
        }
    }
}

static void handle_detection(
    const protocol_frame_t *frame
)
{
    /* ========================================================
     * SET
     *
     * payload[0]
     *
     * 00 = RADAR
     * 01 = CCTV
     * ======================================================== */

    if (
        frame->command ==
        CMD_SET
    )
    {
        if (
            frame->length <
            1
        )
        {
            return;
        }


        uint8_t source =
            frame->payload[0];


        if (
            source ==
            DETECTION_SOURCE_RADAR
        )
        {
            activity_state_t before =
                sleep_manager_get_state();


            detection_manager_set_source(
                DETECTION_SOURCE_RADAR
            );


            music_manager_on_detection_source_changed(
                DETECTION_SOURCE_RADAR
            );


            sleep_manager_reset_activity();


            if (
                before ==
                    ACTIVITY_SLEEPING
                ||
                before ==
                    ACTIVITY_WAIT_AGE
            )
            {
                music_manager_on_wake();
            }
        }
        else if (
            source ==
            DETECTION_SOURCE_CCTV
        )
        {
            activity_state_t before =
                sleep_manager_get_state();


            detection_manager_set_source(
                DETECTION_SOURCE_CCTV
            );


            music_manager_on_detection_source_changed(
                DETECTION_SOURCE_CCTV
            );


            sleep_manager_reset_activity();


            if (
                before ==
                    ACTIVITY_SLEEPING
                ||
                before ==
                    ACTIVITY_WAIT_AGE
            )
            {
                music_manager_on_wake();
            }
        }


        return;
    }


    /* ========================================================
     * DATA
     * ======================================================== */

    if (
        frame->command !=
        CMD_DATA
    )
    {
        return;
    }


    if (
        frame->length <
        1
    )
    {
        return;
    }


    uint8_t event =
        frame->payload[0];


    switch (event)
    {
        /* ====================================================
         * CCTV NEW PERSON
         *
         * [0] EVENT
         * [1..4] EVENT_SEQ
         * ==================================================== */

        case DETECT_EVENT_CCTV_NEW_PERSON:
        {
            if (
                frame->length <
                5
            )
            {
                break;
            }


            uint32_t seq =
                read_u32_be(
                    &frame->payload[1]
                );


            bool accepted =
                detection_manager_cctv_new_person(
                    seq
                );


            s_apply_accepted = accepted;
            if (
                accepted
            )
            {
                activity_state_t before =
                    sleep_manager_get_state();


                bool wait_for_age =
                    music_manager_requires_age_for_wake();


                sleep_manager_on_new_detection(
                    DETECTION_SOURCE_CCTV,
                    seq,
                    wait_for_age
                );


                activity_state_t after =
                    sleep_manager_get_state();


                /*
                * 실제 SLEEPING -> ACTIVE가 된 경우만
                * 음악 Wake 처리.
                *
                * SLEEP_PENDING -> ACTIVE는 현재곡이
                * 계속 재생 중이므로 NEXT 하면 안 됨.
                */
                if (
                    before ==
                        ACTIVITY_SLEEPING
                    &&
                    after ==
                        ACTIVITY_ACTIVE
                )
                {
                    music_manager_on_wake();
                }
            }


            break;
        }


        /* ====================================================
         * CCTV AGE RESULT
         *
         * [0] EVENT
         * [1..4] EVENT_SEQ
         * [5] AGE
         * ==================================================== */

        case DETECT_EVENT_CCTV_AGE_RESULT:
        {
            if (
                frame->length <
                6
            )
            {
                break;
            }


            uint32_t seq =
                read_u32_be(
                    &frame->payload[1]
                );


            age_group_t age =
                (age_group_t)
                frame->payload[5];


            bool accepted =
                detection_manager_cctv_age_result(
                    seq,
                    age
                );


            s_apply_accepted = accepted;
            if (
                accepted
            )
            {
                activity_state_t before =
                    sleep_manager_get_state();


            
                /*
                * AGE group 갱신은 여기서 딱 한 번만 수행.
                */
                music_manager_on_age_result(
                    age
                );


                sleep_manager_on_cctv_age_result(
                    seq,
                    age
                );


                activity_state_t after =
                    sleep_manager_get_state();


                /*
                * 실제 WAIT_AGE -> ACTIVE 전환이 발생했다면
                * 그룹은 이미 위에서 설정했으므로
                * 여기서는 음악 Wake만 처리.
                */
                if (
                    before ==
                        ACTIVITY_WAIT_AGE
                    &&
                    after ==
                        ACTIVITY_ACTIVE
                )
                {
                    music_manager_on_wake();
                }
            }


            break;
        }


        /* ====================================================
         * RADAR NEW PERSON
         *
         * [0] EVENT
         * [1..4] SEQ
         * ==================================================== */

        case DETECT_EVENT_RADAR_NEW_PERSON:
        {
            if (
                frame->length <
                5
            )
            {
                break;
            }


            uint32_t seq =
                read_u32_be(
                    &frame->payload[1]
                );


            bool accepted =
                detection_manager_radar_new_person(
                    seq
                );


            s_apply_accepted = accepted;
            if (
                accepted
            )
            {
                activity_state_t before =
                    sleep_manager_get_state();


                sleep_manager_on_new_detection(
                    DETECTION_SOURCE_RADAR,
                    seq,
                    false
                );


                activity_state_t after =
                    sleep_manager_get_state();


                if (
                    before ==
                        ACTIVITY_SLEEPING
                    &&
                    after ==
                        ACTIVITY_ACTIVE
                )
                {
                    music_manager_on_wake();
                }
            }


            break;
        }


        default:
        {
            break;
        }
    }
}


static void handle_music(
    const protocol_frame_t *frame
)
{
    // APPLY: request_id[4], original command, original payload.
    // RESULT: request_id[4], original command, status, applied detail.
    if (frame->src == NODE_WROOM && frame->command == CMD_APPLY_RESULT) {
        bool info = frame->length >= 7 && (frame->payload[4] == CMD_MUSIC_INFO || frame->payload[4] == CMD_MUSIC_TIMELINE || frame->payload[4] == CMD_MUSIC_SEEK ||
            frame->payload[4] == CMD_MUSIC_CATALOG || frame->payload[4] == CMD_MUSIC_TRACK ||
            frame->payload[4] == CMD_MUSIC_PLAY);
        if (frame->length != 7 && !info) return;
        if (frame->payload[4] == CMD_STOP && frame->payload[5] == 0 &&
            frame->payload[6] == 0) music_policy_on_stopped();
        if(frame->payload[5]==0) {
            if(frame->payload[4]==CMD_START || frame->payload[4]==CMD_NEXT ||
               (frame->payload[4]==CMD_MUSIC_PLAY && frame->length==14 && frame->payload[6]==1))music_policy_on_started();
            else if(frame->payload[4]==CMD_MUSIC_PLAY && frame->length==14 && frame->payload[6]==2)
                music_manager_selected_prepared();
            else if(frame->payload[4]==CMD_PAUSE)music_policy_on_paused();
            else if(frame->payload[4]==CMD_RESUME)music_policy_on_resumed();
        }
        protocol_frame_t result = *frame;
        result.dst = NODE_PI; // Preserve WROOM source: this is the device result.
        xQueueSend(router_queue, &result, portMAX_DELAY);
        return;
    }
    if (frame->src == NODE_PI && frame->command == CMD_APPLY) {
        if (frame->length < 5) return;
        uint8_t op = frame->payload[4];
        bool valid = ((op == CMD_MUSIC_INFO || op == CMD_MUSIC_TIMELINE || op == CMD_MUSIC_CATALOG) && frame->length == 5) ||
            ((op == CMD_MUSIC_TRACK || op == CMD_MUSIC_PLAY) && frame->length == 12 && frame->payload[9] <= 4) ||
            (op == CMD_MUSIC_SEEK && frame->length == 13) ||
            (op == CMD_STOP && frame->length == 5) ||
            (op == CMD_SET && frame->length == 7 &&
             frame->payload[5] == MUSIC_SET_VOLUME && frame->payload[6] <= 100);
        if (op == CMD_MUSIC_PLAY || op == CMD_MUSIC_SEEK) {
            p4_system_state_t state;
            system_state_get(&state);
            valid = valid && music_manager_is_session_enabled() &&
                state.led_mode == LED_MODE_MUSIC && !state.sleep_active && !music_policy_is_blocked();
            if(op==CMD_MUSIC_PLAY) {
                valid = frame->length==12 && frame->payload[9]<=4 &&
                    state.led_mode==LED_MODE_MUSIC && !state.sleep_active &&
                    !(music_policy_get_pause_reasons() & ~MUSIC_PAUSE_REASON_USER);
            }
        }
        if (!valid || call_manager_is_active() || emergency_manager_is_active()) {
            protocol_frame_t result = *frame;
            result.src = NODE_P4; result.dst = NODE_PI;
            result.command = CMD_APPLY_RESULT; result.length = 7;
            result.payload[5] = 1; result.payload[6] = 0;
            xQueueSend(router_queue, &result, portMAX_DELAY);
            return;
        }
        if (op == CMD_STOP) music_manager_disable_session();
        protocol_frame_t request = *frame;
        request.src = NODE_P4; request.dst = NODE_WROOM;
        xQueueSend(router_queue, &request, portMAX_DELAY);
        return;
    }
    /* ========================================================
     * WROOM -> P4 EVENT
     * ======================================================== */

    if (
        frame->src ==
        NODE_WROOM
    )
    {
        if (
            frame->command !=
                CMD_DATA
            ||
            frame->length <
                1
        )
        {
            return;
        }


        uint8_t event =
            frame->payload[0];


        switch (
            event
        )
        {
            case MUSIC_EVENT_STARTED:
            {
                music_policy_on_started();


                ESP_LOGI(
                    TAG,
                    "MUSIC STARTED"
                );


                break;
            }


            case MUSIC_EVENT_FINISHED:
            {
                activity_state_t before =
                    sleep_manager_get_state();


                music_policy_on_finished();


                ESP_LOGI(
                    TAG,
                    "MUSIC FINISHED"
                );


                sleep_manager_on_music_finished();


                activity_state_t after =
                    sleep_manager_get_state();


                bool entered_sleep =
                    (
                        before ==
                            ACTIVITY_SLEEP_PENDING
                        &&
                        after ==
                            ACTIVITY_SLEEPING
                    );


                music_manager_on_track_finished(
                    entered_sleep
                );


                break;
            }


            case MUSIC_EVENT_PAUSED:
            {
                music_policy_on_paused();


                ESP_LOGI(
                    TAG,
                    "MUSIC PAUSED"
                );


                break;
            }


            case MUSIC_EVENT_RESUMED:
            {
                music_policy_on_resumed();


                ESP_LOGI(
                    TAG,
                    "MUSIC RESUMED"
                );


                break;
            }


            case MUSIC_EVENT_STOPPED:
            {
                music_policy_on_stopped();


                ESP_LOGI(
                    TAG,
                    "MUSIC STOPPED"
                );


                break;
            }


            case MUSIC_EVENT_ERROR:
            {
                music_policy_on_error();


                ESP_LOGW(
                    TAG,
                    "MUSIC ERROR"
                );


                break;
            }


            default:
            {
                break;
            }
        }


        return;
    }


    /* ========================================================
     * PI -> P4 MUSIC CONTROL
     *
     * 이제 관제는 WROOM을 직접 제어하지 않고
     * P4에 음악 명령을 준다.
     * ======================================================== */

    if (
        frame->src !=
        NODE_PI
    )
    {
        return;
    }


    switch (
        frame->command
    )
    {
        case CMD_START:
        {
            music_manager_start();

            break;
        }


        case CMD_STOP:
        {
            music_manager_stop();

            break;
        }


        case CMD_PAUSE:
        {
            music_manager_user_pause();

            break;
        }


        case CMD_RESUME:
        {
            music_manager_user_resume();

            break;
        }


        case CMD_NEXT:
        {
            music_manager_next();

            break;
        }


        case CMD_SET:
        {
            if (
                frame->length <
                2
            )
            {
                break;
            }


            uint8_t type =
                frame->payload[0];


            uint8_t value =
                frame->payload[1];


            if (
                type ==
                MUSIC_SET_PLAY_MODE
            )
            {
                if (
                    !music_manager_set_mode(
                        (music_play_mode_t)
                        value
                    )
                )
                {
                    ESP_LOGW(
                        TAG,
                        "Music mode rejected=%u",
                        value
                    );
                }
            }


            else if (type == MUSIC_SET_VOLUME) {
                if (value > 100) {
                    ESP_LOGW(TAG, "Volume rejected=%u", value);
                    break;
                }
                protocol_frame_t volume = *frame;
                volume.src = NODE_P4;
                volume.dst = NODE_WROOM;
                volume.length = 2;
                xQueueSend(router_queue, &volume, portMAX_DELAY);
                ESP_LOGI(TAG, "WROOM volume request=%u%%", value);
            }

            /*
             * MUSIC_SET_GROUP는 Pi에서 직접 사용하지 않는다.
             *
             * AGE 그룹은 CCTV AGE_RESULT를 받은 P4가
             * 자동으로 결정한다.
             */


            break;
        }


        default:
        {
            break;
        }
    }
}


static void handle_sleep(
    const protocol_frame_t *frame
)
{
    switch (
        frame->command
    )
    {
        case CMD_START:
        {
            sleep_manager_set_enabled(
                true
            );


            break;
        }


        case CMD_STOP:
        {
            sleep_manager_set_enabled(
                false
            );


            break;
        }


        default:
        {
            break;
        }
    }
}

static void handle_audio(
    const protocol_frame_t *frame
)
{
    if (frame->command == CMD_CALL_KEEPALIVE) {
        if (frame->src == NODE_PI && frame->length == 4 &&
            call_manager_session_matches(read_u32_be(frame->payload)))
            call_manager_keepalive();
        return;
    }
    switch (
        frame->command
    )
    {
        /* ====================================================
         * CALL CONNECT
         *
         * 관제에서 일반 통화 연결
         * ==================================================== */

        case CMD_START:
        {
            if (frame->src == NODE_PI && frame->length == 4 &&
                call_manager_bind_session(read_u32_be(frame->payload)))
                call_manager_start(CALL_ORIGIN_NORMAL);


            break;
        }


        /* ====================================================
         * CALL END
         * ==================================================== */

        case CMD_STOP:
        {
            if (frame->src == NODE_PI && frame->length == 4)
                call_manager_stop_session(read_u32_be(frame->payload));


            break;
        }


        /* ====================================================
         * PTT DIRECTION
         *
         * payload[0]
         *
         * 01 FIELD_TX
         * 02 CONTROL_TX
         * ==================================================== */

        case CMD_SET:
        {
            if (
                frame->length <
                1
            )
            {
                break;
            }


            audio_direction_t direction =
                (audio_direction_t)
                frame->payload[0];


            if (frame->src == NODE_PI && frame->length == 9)
                call_manager_set_direction_ordered(read_u32_be(frame->payload+1),
                    read_u32_be(frame->payload+5), direction);


            break;
        }


        /* ====================================================
         * 실제 Codec2 음성 DATA는 다음 단계에서 처리.
         *
         * 일반적으로 Voice frame은 DST를 PI/WROOM/S3로
         * 직접 잡아 Router가 전달하게 만들 예정.
         * ==================================================== */

        case CMD_DATA:
        {
            call_manager_handle_readiness(frame);
            break;
        }


        default:
        {
            break;
        }
    }
}

static void handle_emergency(
    const protocol_frame_t *frame
)
{
    /*
     * S3 -> P4
     */
    if (
        frame->src ==
        NODE_S3
    )
    {
        if (
            frame->length <
            5
        )
        {
            return;
        }


        uint8_t source =
            frame->payload[0];


        uint32_t seq =
            read_u32_be(
                &frame->payload[1]
            );


        if (
            frame->command ==
            CMD_START
        )
        {
            emergency_manager_start(
                source,
                seq
            );


            return;
        }


        if (
            frame->command ==
            CMD_STOP
        )
        {
            emergency_manager_cancel(
                source,
                seq
            );


            return;
        }


        return;
    }


    /*
     * Raspberry Pi -> P4
     *
     * 관제 ACK
     */
    if (
        frame->src ==
        NODE_PI
        &&
        frame->command ==
            CMD_SET
    )
    {
        if (
            frame->length <
            5
        )
        {
            return;
        }


        if (
            frame->payload[0]
            !=
            EMERGENCY_ACTION_ACK
        )
        {
            return;
        }


        uint32_t seq =
            read_u32_be(
                &frame->payload[1]
            );


        if (frame->length == 9)
            emergency_manager_ack_session(seq, read_u32_be(frame->payload+5));
    }
}
