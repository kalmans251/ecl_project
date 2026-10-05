#pragma once
/* Decoder-only state: destroy with voice_decoder_destroy, never codec2_destroy. */
struct CODEC2;
struct CODEC2 *voice_decoder_create(void);
void voice_decoder_destroy(struct CODEC2 *decoder);
