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