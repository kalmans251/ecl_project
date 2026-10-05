"""Compare pinned decoder output and exercise every constructor allocation failure.
ECL_TEST_CODEC2_SRC points to pinned Codec2 src; ECL_TEST_CODEC2_LIB to its .so.
"""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

MAIN = Path(__file__).resolve().parents[1] / 'main'
SRC = os.environ.get('ECL_TEST_CODEC2_SRC')
LIB = os.environ.get('ECL_TEST_CODEC2_LIB')
HARNESS = r"""
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>
#include <math.h>
#include "codec2.h"
#include "codec2_internal.h"
static int attempt, fail_at, live;
static void *checked_calloc(size_t n, size_t size) {
    if (++attempt == fail_at) return NULL;
    void *p = calloc(n, size); if (p) ++live; return p;
}
static void checked_free(void *p) { if (p) --live; free(p); }
static codec2_fftr_cfg checked_fft(int n, int inverse, void *mem, size_t *len) {
    if (++attempt == fail_at) return NULL;
    codec2_fftr_cfg p = codec2_fftr_alloc(n, inverse, mem, len);
    if (p) ++live; return p;
}
static void checked_fft_free(codec2_fftr_cfg p) {
    if (p) --live; codec2_fftr_free(p);
}
#define calloc checked_calloc
#define free checked_free
#define codec2_fftr_alloc checked_fft
#define codec2_fftr_free checked_fft_free
#include "voice_decoder.c"
#undef calloc
#undef free
#undef codec2_fftr_alloc
#undef codec2_fftr_free
int main(int argc, char **argv) {
    (void)argc;
    for (fail_at = 1; fail_at <= 5; ++fail_at) {
        attempt = 0;
        assert(voice_decoder_create() == NULL);
        assert(live == 0);
    }
    fail_at = 0; attempt = 0;
    struct CODEC2 *small = voice_decoder_create();
    struct CODEC2 *full = codec2_create(CODEC2_MODE_2400);
    struct CODEC2 *encoder = codec2_create(CODEC2_MODE_2400);
    assert(small && full && encoder && live == 5);
    assert(!small->nlp && !small->fft_fwd_cfg && !small->bpf_buf);
    short input[160], a[160]; unsigned char bits[6];
    for (int frame = 0; frame < 200; ++frame) {
        for (int i = 0; i < 160; ++i)
            input[i] = 5000 * sin((frame * 160 + i) * 0.11);
        codec2_encode(encoder, bits, input);
        codec2_decode(argv[1][0] == 'f' ? full : small, a, bits);
        fwrite(a, sizeof(short), 160, stdout);

    }
    voice_decoder_destroy(small); assert(live == 0);
    voice_decoder_destroy(NULL);
    codec2_destroy(full); codec2_destroy(encoder);

}
"""
class DecoderTests(unittest.TestCase):
    @unittest.skipUnless(SRC and LIB, 'requires pinned Codec2 source and library')
    def test_decoder(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'test.c'
            source.write_text(HARNESS)
            binary = Path(folder) / 'test'
            subprocess.run(['cc', '-std=c11', '-fsingle-precision-constant',
                '-I', str(MAIN), '-I', SRC, str(source), LIB, '-lm',
                '-o', str(binary)], check=True)
            full = subprocess.run([str(binary), 'full'], check=True, timeout=10, capture_output=True)
            small = subprocess.run([str(binary), 'small'], check=True, timeout=10, capture_output=True)
            self.assertEqual(full.stdout, small.stdout)
