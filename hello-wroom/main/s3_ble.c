#include "s3_ble.h"

#include <string.h>

#include "board_config.h"
#include "s3_task.h"

#include "esp_err.h"
#include "esp_log.h"

#include "nvs_flash.h"

#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"

#include "host/ble_hs.h"
#include "host/ble_gatt.h"
#include "host/ble_uuid.h"
#include "host/util/util.h"

#include "nimble/nimble_port.h"
#include "nimble/nimble_port_freertos.h"

#include "os/os_mbuf.h"


static const char *TAG =
    "S3_BLE";


/* ============================================================
 * UUID
 *
 * Service:
 * 7a100001-8e7f-4b6c-9a2d-100000000001
 *
 * Write:
 * ...0002
 *
 * Notify:
 * ...0003
 * ============================================================ */

static const ble_uuid128_t
s_service_uuid =
    BLE_UUID128_INIT(
        0x01, 0x00, 0x00, 0x00,
        0x00, 0x10, 0x2d, 0x9a,
        0x6c, 0x4b, 0x7f, 0x8e,
        0x01, 0x00, 0x10, 0x7a
    );


static const ble_uuid128_t
s_write_uuid =
    BLE_UUID128_INIT(
        0x02, 0x00, 0x00, 0x00,
        0x00, 0x10, 0x2d, 0x9a,
        0x6c, 0x4b, 0x7f, 0x8e,
        0x02, 0x00, 0x10, 0x7a
    );


static const ble_uuid128_t
s_notify_uuid =
    BLE_UUID128_INIT(
        0x03, 0x00, 0x00, 0x00,
        0x00, 0x10, 0x2d, 0x9a,
        0x6c, 0x4b, 0x7f, 0x8e,
        0x03, 0x00, 0x10, 0x7a
    );


static uint8_t
s_own_addr_type =
    0;


static uint16_t
s_conn_handle =
    BLE_HS_CONN_HANDLE_NONE;


static uint16_t
s_service_start =
    0;


static uint16_t
s_service_end =
    0;


static uint16_t
s_write_handle =
    0;


static uint16_t
s_notify_handle =
    0;


static volatile bool
s_ready =
    false;


static SemaphoreHandle_t
s_send_mutex =
    NULL;


static void start_scan(void);


/* ============================================================
 * NAME MATCH
 * ============================================================ */

static bool name_matches(
    const struct ble_hs_adv_fields *fields
)
{
    if (
        fields == NULL ||
        fields->name == NULL ||
        fields->name_len == 0
    )
    {
        return false;
    }


    size_t wanted_len =
        strlen(
            S3_BLE_DEVICE_NAME
        );


    return
        fields->name_len ==
        wanted_len
        &&
        memcmp(
            fields->name,

            S3_BLE_DEVICE_NAME,

            wanted_len
        )
        ==
        0;
}


/* ============================================================
 * WRITE CALLBACK
 * ============================================================ */

static int gatt_write_cb(
    uint16_t conn_handle,

    const struct ble_gatt_error *error,

    struct ble_gatt_attr *attr,

    void *arg
)
{
    (void)conn_handle;
    (void)attr;
    (void)arg;


    if (
        error != NULL &&
        error->status != 0
    )
    {
        ESP_LOGW(
            TAG,
            "GATT write status=%d",
            error->status
        );
    }


    return 0;
}


/* ============================================================
 * SUBSCRIBE NOTIFY
 * ============================================================ */

static void subscribe_notify(void)
{
    if (
        s_conn_handle ==
        BLE_HS_CONN_HANDLE_NONE
        ||
        s_write_handle ==
        0
        ||
        s_notify_handle ==
        0
    )
    {
        ESP_LOGE(
            TAG,
            "Characteristic handles missing write=%u notify=%u",
            s_write_handle,
            s_notify_handle
        );

        s_ready =
            false;

        return;
    }


    /*
     * 현재 S3 Arduino BLE 구조:
     *
     * Notify Value Handle
     * 바로 다음 handle = CCCD
     */

    uint16_t cccd_handle =
        s_notify_handle +
        1;


    uint8_t enable_notify[2] =
    {
        0x01,
        0x00
    };


    int rc =
        ble_gattc_write_flat(
            s_conn_handle,

            cccd_handle,

            enable_notify,

            sizeof(enable_notify),

            gatt_write_cb,

            NULL
        );


    if (
        rc ==
        0
    )
    {
        s_ready =
            s_write_handle !=
            0;


        ESP_LOGI(
            TAG,
            "Notify subscribe requested write=%u notify=%u cccd=%u",
            s_write_handle,
            s_notify_handle,
            cccd_handle
        );
    }
    else
    {
        ESP_LOGW(
            TAG,
            "Notify subscribe rc=%d",
            rc
        );
    }
}


/* ============================================================
 * CHARACTERISTIC DISCOVERY
 * ============================================================ */

static int chr_disc_cb(
    uint16_t conn_handle,

    const struct ble_gatt_error *error,

    const struct ble_gatt_chr *chr,

    void *arg
)
{
    (void)conn_handle;
    (void)arg;


    if (
        error->status ==
        BLE_HS_EDONE
    )
    {
        ESP_LOGI(
            TAG,
            "Characteristic discovery done"
        );


        subscribe_notify();


        return 0;
    }


    if (
        error->status != 0 ||
        chr == NULL
    )
    {
        return 0;
    }


    if (
        ble_uuid_cmp(
            &chr->uuid.u,
            &s_write_uuid.u
        )
        ==
        0
    )
    {
        s_write_handle =
            chr->val_handle;


        ESP_LOGI(
            TAG,
            "WRITE handle=%u",
            s_write_handle
        );
    }
    else if (
        ble_uuid_cmp(
            &chr->uuid.u,
            &s_notify_uuid.u
        )
        ==
        0
    )
    {
        s_notify_handle =
            chr->val_handle;


        ESP_LOGI(
            TAG,
            "NOTIFY handle=%u",
            s_notify_handle
        );
    }


    return 0;
}


/* ============================================================
 * SERVICE DISCOVERY
 * ============================================================ */

static int svc_disc_cb(
    uint16_t conn_handle,

    const struct ble_gatt_error *error,

    const struct ble_gatt_svc *service,

    void *arg
)
{
    (void)arg;


    if (
        error->status ==
        BLE_HS_EDONE
    )
    {
        return 0;
    }


    if (
        error->status != 0 ||
        service == NULL
    )
    {
        return 0;
    }


    s_service_start =
        service->start_handle;


    s_service_end =
        service->end_handle;


    ESP_LOGI(
        TAG,
        "Service %u ~ %u",
        s_service_start,
        s_service_end
    );


    ble_gattc_disc_all_chrs(
        conn_handle,

        s_service_start,

        s_service_end,

        chr_disc_cb,

        NULL
    );


    return 0;
}


/* ============================================================
 * MTU
 * ============================================================ */

static int mtu_cb(
    uint16_t conn_handle,

    const struct ble_gatt_error *error,

    uint16_t mtu,

    void *arg
)
{
    (void)conn_handle;
    (void)arg;


    if (
        error != NULL &&
        error->status == 0
    )
    {
        ESP_LOGI(
            TAG,
            "MTU=%u",
            mtu
        );
    }


    return 0;
}


/* ============================================================
 * GAP EVENT
 * ============================================================ */

static int gap_event(
    struct ble_gap_event *event,

    void *arg
)
{
    (void)arg;


    switch (
        event->type
    )
    {
        /* ====================================================
         * SCAN RESULT
         * ==================================================== */

        case BLE_GAP_EVENT_DISC:
        {
            struct ble_hs_adv_fields fields;


            memset(
                &fields,
                0,
                sizeof(fields)
            );


            if (
                ble_hs_adv_parse_fields(
                    &fields,

                    event->disc.data,

                    event->disc.length_data
                )
                !=
                0
            )
            {
                return 0;
            }


            if (
                !name_matches(
                    &fields
                )
            )
            {
                return 0;
            }


            ESP_LOGI(
                TAG,
                "Found %s",
                S3_BLE_DEVICE_NAME
            );


            ble_gap_disc_cancel();


            int rc =
                ble_gap_connect(
                    s_own_addr_type,

                    &event->disc.addr,

                    30000,

                    NULL,

                    gap_event,

                    NULL
                );


            if (
                rc !=
                0
            )
            {
                ESP_LOGW(
                    TAG,
                    "Connect rc=%d",
                    rc
                );


                start_scan();
            }


            return 0;
        }


        /* ====================================================
         * CONNECT
         * ==================================================== */

        case BLE_GAP_EVENT_CONNECT:
        {
            if (
                event->connect.status !=
                0
            )
            {
                ESP_LOGW(
                    TAG,
                    "Connect failed=%d",
                    event->connect.status
                );


                start_scan();


                return 0;
            }


            s_conn_handle =
                event->connect.conn_handle;


            s_ready =
                false;


            s_write_handle =
                0;


            s_notify_handle =
                0;


            ESP_LOGI(
                TAG,
                "S3 connected"
            );


            ble_gattc_exchange_mtu(
                s_conn_handle,

                mtu_cb,

                NULL
            );


            ble_gattc_disc_svc_by_uuid(
                s_conn_handle,

                &s_service_uuid.u,

                svc_disc_cb,

                NULL
            );


            return 0;
        }


        /* ====================================================
         * DISCONNECT
         * ==================================================== */

        case BLE_GAP_EVENT_DISCONNECT:
        {
            ESP_LOGW(
                TAG,
                "Disconnected reason=%d",
                event->disconnect.reason
            );


            s_ready =
                false;


            s_conn_handle =
                BLE_HS_CONN_HANDLE_NONE;


            s_write_handle =
                0;


            s_notify_handle =
                0;


            start_scan();


            return 0;
        }


        /* ====================================================
         * NOTIFY
         * ==================================================== */

        case BLE_GAP_EVENT_NOTIFY_RX:
        {
            if (
                event->notify_rx.attr_handle !=
                s_notify_handle
            )
            {
                return 0;
            }


            int len =
                OS_MBUF_PKTLEN(
                    event->notify_rx.om
                );


            if (
                len <=
                0
            )
            {
                return 0;
            }


            uint8_t temp[
                256
            ];


            int copy_len =
                len;


            if (
                copy_len >
                (int)sizeof(temp)
            )
            {
                copy_len =
                    sizeof(temp);
            }


            if (
                os_mbuf_copydata(
                    event->notify_rx.om,

                    0,

                    copy_len,

                    temp
                )
                ==
                0
            )
            {
                s3_task_on_ble_rx(
                    temp,
                    copy_len
                );
            }


            return 0;
        }


        default:
        {
            return 0;
        }
    }
}


/* ============================================================
 * SCAN
 * ============================================================ */

static void start_scan(void)
{
    struct ble_gap_disc_params params;


    memset(
        &params,
        0,
        sizeof(params)
    );


    params.passive =
        0;


    params.filter_duplicates =
        1;


    int rc =
        ble_gap_disc(
            s_own_addr_type,

            BLE_HS_FOREVER,

            &params,

            gap_event,

            NULL
        );


    if (
        rc ==
        0
    )
    {
        ESP_LOGI(
            TAG,
            "Scanning S3..."
        );
    }
    else
    {
        ESP_LOGW(
            TAG,
            "Scan rc=%d",
            rc
        );
    }
}


/* ============================================================
 * SYNC
 * ============================================================ */

static void on_sync(void)
{
    int rc =
        ble_hs_id_infer_auto(
            0,

            &s_own_addr_type
        );


    if (
        rc !=
        0
    )
    {
        ESP_LOGE(
            TAG,
            "ble_hs_id_infer_auto=%d",
            rc
        );


        return;
    }


    ESP_LOGI(
        TAG,
        "NimBLE synchronized"
    );


    start_scan();
}


/* ============================================================
 * HOST TASK
 * ============================================================ */

static void host_task(
    void *param
)
{
    (void)param;


    ESP_LOGI(
        TAG,
        "NimBLE host task start"
    );


    nimble_port_run();


    nimble_port_freertos_deinit();
}


/* ============================================================
 * INIT
 * ============================================================ */

bool s3_ble_init(void)
{
    esp_err_t nvs =
        nvs_flash_init();


    if (
        nvs ==
        ESP_ERR_NVS_NO_FREE_PAGES
        ||
        nvs ==
        ESP_ERR_NVS_NEW_VERSION_FOUND
    )
    {
        ESP_ERROR_CHECK(
            nvs_flash_erase()
        );


        ESP_ERROR_CHECK(
            nvs_flash_init()
        );
    }
    else if (
        nvs !=
        ESP_OK
    )
    {
        return false;
    }


    if (
        nimble_port_init() !=
        ESP_OK
    )
    {
        ESP_LOGE(
            TAG,
            "nimble_port_init failed"
        );


        return false;
    }


    ble_hs_cfg.sync_cb =
        on_sync;


    s_send_mutex =
        xSemaphoreCreateMutex();


    if (
        s_send_mutex ==
        NULL
    )
    {
        return false;
    }


    nimble_port_freertos_init(
        host_task
    );


    ESP_LOGI(
        TAG,
        "S3 BLE Central initialized"
    );


    return true;
}


/* ============================================================
 * READY
 * ============================================================ */

bool s3_ble_is_ready(void)
{
    return s_ready;
}


/* ============================================================
 * SEND
 * ============================================================ */

bool s3_ble_send(
    const uint8_t *data,
    size_t len
)
{
    if (
        data == NULL ||
        len == 0 ||
        !s_ready ||
        s_conn_handle ==
        BLE_HS_CONN_HANDLE_NONE ||
        s_write_handle == 0
    )
    {
        return false;
    }


    /*
     * MTU 185 사용 기준.
     */

    if (
        len >
        180
    )
    {
        return false;
    }


    if (
        xSemaphoreTake(
            s_send_mutex,
            pdMS_TO_TICKS(100)
        )
        !=
        pdTRUE
    )
    {
        return false;
    }


    int rc =
        ble_gattc_write_flat(
            s_conn_handle,

            s_write_handle,

            data,

            len,

            gatt_write_cb,

            NULL
        );


    xSemaphoreGive(
        s_send_mutex
    );


    return
        rc ==
        0;
}