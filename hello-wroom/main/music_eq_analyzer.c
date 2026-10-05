#include "music_eq_analyzer.h"
#include <math.h>
#include <string.h>
#define PI_F 3.14159265358979323846f
#define ANALYSIS_RATE 16000U
#define REPORT_SAMPLES 1600U

void music_eq_analyzer_reset(music_eq_analyzer_t *s)
{
    memset(s, 0, sizeof(*s));
    for (unsigned i = 0; i < MUSIC_EQ_FFT_SIZE; ++i)
        s->window[i] = 0.5f - 0.5f * cosf(2 * PI_F * i / MUSIC_EQ_FFT_SIZE);
}

static void spectrum(music_eq_analyzer_t *s)
{
    const unsigned n = MUSIC_EQ_FFT_SIZE;
    for (unsigned i = 0; i < n; ++i) {
        s->real[i] *= s->window[i];
        s->imag[i] = 0;
    }
    for (unsigned i = 1, j = 0; i < n; ++i) {
        unsigned bit = n >> 1;
        for (; j & bit; bit >>= 1) j ^= bit;
        j ^= bit;
        if (i < j) { float t=s->real[i]; s->real[i]=s->real[j]; s->real[j]=t; }
    }
    for (unsigned len = 2; len <= n; len <<= 1) {
        float step_r=cosf(-2 * PI_F / len), step_i=sinf(-2 * PI_F / len);
        for (unsigned i = 0; i < n; i += len) {
            float wr=1, wi=0;
            for (unsigned j = 0; j < len/2; ++j) {
                unsigned a=i+j, b=a+len/2;
                float tr=wr*s->real[b]-wi*s->imag[b];
                float ti=wr*s->imag[b]+wi*s->real[b];
                s->real[b]=s->real[a]-tr; s->imag[b]=s->imag[a]-ti;
                s->real[a]+=tr; s->imag[a]+=ti;
                float next=wr*step_r-wi*step_i;
                wi=wr*step_i+wi*step_r; wr=next;
            }
        }
    }
    /* Bin boundaries in Hz: 0,125,250,500,1000,2000,4000,6000,8000.
     * Exclude DC. Normalize Hann-window energy to RMS relative to full scale.
     */
    const unsigned edges[9]={0,2,4,8,16,32,64,96,128};
    float amplitudes[MUSIC_EQ_BANDS], peak=0;
    for (unsigned band=0; band<MUSIC_EQ_BANDS; ++band) {
        float power=0;
        unsigned start=edges[band] ? edges[band] : 1;
        for (unsigned k=start; k<edges[band+1]; ++k)
            power+=s->real[k]*s->real[k]+s->imag[k]*s->imag[k];
        amplitudes[band]=sqrtf(2 * power / (0.375f*n*n));
        if (amplitudes[band]>peak) peak=amplitudes[band];
    }
    /* Follow the recent peak quickly upward and slowly downward (~2 s).
     * Keep a silence floor so background noise is not expanded to full height.
     */
    if (peak>s->reference) s->reference=peak;
    else s->reference+=0.008f*(peak-s->reference);
    float reference=fmaxf(s->reference,0.002f);
    for (unsigned band=0; band<MUSIC_EQ_BANDS; ++band) {
        float rms=amplitudes[band];
        float level=rms>0.0005f ? 255.0f*sqrtf(rms/reference) : 0;
        if (level>255) level=255;
        float mix=level>s->smoothed[band] ? 0.7f : 0.15f;
        s->smoothed[band]+=mix*(level-s->smoothed[band]);
    }
    s->filled=0;
}

bool music_eq_analyze(music_eq_analyzer_t *s, const int16_t *pcm,
                      size_t frames, unsigned rate, uint8_t levels[8])
{
    if (!pcm || !frames || rate<8000 || rate>48000) return false;
    if (rate!=s->input_rate) {
        music_eq_analyzer_reset(s);
        s->input_rate=rate;
    }
    bool report=false;
    for (size_t i=0; i<frames; ++i) {
        /* Average the source samples contributing to a 16kHz sample.
         * At 8/12kHz repeat samples. At 44.1/48kHz use a fractional box decimator.
         * This is display analysis, not the speaker's playback path.
         */
        s->average_sum+=pcm[i]/32768.0f;
        ++s->average_count;
        s->phase+=ANALYSIS_RATE;
        if (s->phase>=rate) {
            float sample=s->average_sum/s->average_count;
            do {
                s->real[s->filled++]=sample;
                if (s->filled==MUSIC_EQ_FFT_SIZE) spectrum(s);
                if (++s->report_samples>=REPORT_SAMPLES) {
                    s->report_samples-=REPORT_SAMPLES;
                    report=true;
                }
                s->phase-=rate;
            } while (s->phase>=rate);
            s->average_sum=0; s->average_count=0;
        }
    }
    if (report)
        for (unsigned i=0; i<8; ++i) levels[i]=(uint8_t)(s->smoothed[i]+0.5f);
    return report;
}
