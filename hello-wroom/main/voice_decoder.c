/* Codec2 2400 decoder initialization, matched to the pinned Codec2 revision.
 * Encoder pitch analysis, analysis FFT and input filters are intentionally absent.
 * Internal state layout must be rechecked when the Codec2 dependency changes.
 */
#include <stdio.h>
#include <stdlib.h>
#include "codec2.h"
#include "codec2_internal.h"
#include "sine.h"
#include "quantise.h"
#include "voice_decoder.h"

extern void codec2_decode_2400(struct CODEC2 *, short [], const unsigned char *);

void voice_decoder_destroy(struct CODEC2 *c2)
{
    if (!c2) return;
    if (c2->fftr_fwd_cfg) codec2_fftr_free(c2->fftr_fwd_cfg);
    if (c2->fftr_inv_cfg) codec2_fftr_free(c2->fftr_inv_cfg);
    free(c2->Pn);
    free(c2->Sn_);
    free(c2);
}

struct CODEC2 *voice_decoder_create(void)
{
    struct CODEC2 *c2 = calloc(1, sizeof(*c2));
    if (!c2) return NULL;
    c2->mode = CODEC2_MODE_2400;
    c2->c2const = c2const_create(8000, N_S);
    c2->Fs = c2->c2const.Fs;
    c2->n_samp = c2->c2const.n_samp;
    c2->m_pitch = c2->c2const.m_pitch;
    c2->Pn = calloc(2 * c2->n_samp, sizeof(float));
    if (!c2->Pn) goto failed;
    c2->Sn_ = calloc(2 * c2->n_samp, sizeof(float));
    if (!c2->Sn_) goto failed;
    c2->fftr_fwd_cfg = codec2_fftr_alloc(FFT_ENC, 0, NULL, NULL);
    if (!c2->fftr_fwd_cfg) goto failed;
    c2->fftr_inv_cfg = codec2_fftr_alloc(FFT_DEC, 1, NULL, NULL);
    if (!c2->fftr_inv_cfg) goto failed;
    make_synthesis_window(&c2->c2const, c2->Pn);
    c2->prev_model_dec.Wo = (float)TWO_PI / c2->c2const.p_max;
    c2->prev_model_dec.L = (float)PI / c2->prev_model_dec.Wo;
    for (int i = 0; i < LPC_ORD; ++i)
        c2->prev_lsps_dec[i] = i * (float)PI / (LPC_ORD + 1);
    c2->prev_e_dec = 1;
    c2->lpc_pf = c2->bass_boost = 1;
    c2->beta = LPCPF_BETA;
    c2->gamma = LPCPF_GAMMA;
    c2->post_filter_en = true;
    c2->gray = 1;
    c2->decode = codec2_decode_2400;
    return c2;
failed:
    voice_decoder_destroy(c2);
    return NULL;
}
