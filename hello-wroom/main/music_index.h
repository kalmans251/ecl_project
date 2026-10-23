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
    uint32_t next_offset;
    bool ready;
} music_index_t;
typedef ssize_t (*music_index_read_fn)(void *, uint8_t *, size_t);
bool music_index_scan(music_index_t *, mp3dec_t *, uint8_t *, size_t,
                      uint32_t, music_index_read_fn, void *);
bool music_index_locate(const music_index_t *, uint32_t, uint32_t *, uint64_t *);

/* Probe only the first MPEG frame after ID3. No guessed CBR duration or TLEN. */
typedef struct {
    uint32_t duration_ms, hz, frame_samples;
    const char *source;
} music_header_info_t;
bool music_header_probe(const uint8_t *, size_t, uint64_t, music_header_info_t *);
/* Stop once the requested sample is indexed; UINT32_MAX requests the whole file. */
bool music_index_scan_to(music_index_t *, mp3dec_t *, uint8_t *, size_t,
                         uint32_t, music_index_read_fn, void *, uint32_t);

/* Resume only a validated contiguous prefix; caller positions reader at next_offset. */
bool music_index_extend_to(music_index_t *, mp3dec_t *, uint8_t *, size_t,
                          uint32_t, music_index_read_fn, void *, uint32_t);
bool music_index_append(music_index_t *, uint32_t offset, uint32_t end,
                        uint64_t sample, uint32_t hz, uint32_t frame_samples);
bool music_index_cache_load(const char *path, int fd, uint32_t start, music_index_t *);
bool music_index_cache_save(const char *path, int fd, uint32_t start, const music_index_t *);
