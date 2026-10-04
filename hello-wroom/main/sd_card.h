#pragma once

#include <stdbool.h>

#include "sdmmc_cmd.h"


bool sd_card_init(void);


void sd_card_deinit(void);


bool sd_card_is_mounted(void);


sdmmc_card_t *sd_card_get(void);


void sd_card_print_info(void);


void sd_card_list_directory(
    const char *path
);

/*
 * 현재 mount된 SD 카드가 실제로 응답하는지 확인.
 *
 * true  = 정상
 * false = 제거됨 / 통신 실패 / mount 안 됨
 */
bool sd_card_check_health(void);