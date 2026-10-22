#pragma once
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <sys/types.h>
#include "minimp3.h"
#define MUSIC_INDEX_POINTS 128
/* Sparse offsets; no allocation and no decoder PCM work during the scan. */
typedef struct {
    uint32_t offsets[MUSIC_INDEX_POINTS];
    uint64_t samples[MUSIC_INDEX_POINTS];
    uint64_t total_samples;
    uint32_t hz, frame_samples, stride, frames;
    unsigned count;
    bool ready;
} music_index_t;
typedef ssize_t (*music_index_read_fn)(void *, uint8_t *, size_t);
bool music_index_scan(music_index_t *, mp3dec_t *, uint8_t *, size_t,
                      uint32_t, music_index_read_fn, void *);
bool music_index_locate(const music_index_t *, uint32_t, uint32_t *, uint64_t *);
