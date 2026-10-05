Run host tests against the exact Codec2 revision pinned in components/codec2/CMakeLists.txt:

```sh
ECL_TEST_CODEC2_SRC=/path/to/codec2/src ECL_TEST_CODEC2_LIB=/path/to/pinned-libcodec2.so python -m unittest discover -s hello-wroom/tests -v
```

The decoder test compares 200 frames of PCM byte for byte against codec2_create(2400), using separate processes to keep the library global excitation RNG identical. It injects failure at all five decoder allocations and checks complete cleanup. The worker test runs actual session code with RTOS/I2S substitutes and the real decoder.

WROOM uses decoder-only state because the full Codec2 constructor allocates unused encoder FFT, pitch analysis and input filters. Its internal layout is tied to the pinned Codec2 source: rerun equivalence tests and audit constructor fields when updating that dependency. Always pair voice_decoder_create with voice_decoder_destroy.

Hardware: rebuild and flash WROOM, establish the call, run `ptt 1 on`, then `python tools/voice_send.py --railing 1 --tone --seconds 10` on Pi. Expect `Codec2 PLAY` with no reset. Record the decoder heap diagnostic and playback stack-free diagnostic. Allocation failure should log an error and keep the firmware running. Actual heap availability and audible continuity require hardware verification.

Voice PCM remains Codec2 8kHz; I2S is 16kHz stereo using two copies per mono sample (zero-order hold). The worker test checks exact ramp samples, stereo duplication, silence, and 20ms frame size. `pcm_peak` is the decoded packet peak before volume scaling (0 means silent PCM; range 0..32768). It does not verify the physical DAC output.

The audio-output test compiles actual audio_output.c with driver substitutes and models the ESP-IDF TX auto-clear contract: after music stops supplying PCM, completed DMA descriptors must emit zero rather than repeat old samples. It also checks resume, zero volume, rate change and channel reinitialization. Hardware pause/underrun timing still needs board testing.

The music EQ tests compile the actual analyzer and forwarding wrapper. They check tone-band selection, input sample rates, quiet-content auto sensitivity and silence, reporting cadence, eight-byte protocol framing, queue-full behavior, allocation failure, mailbox overwrite/copy ownership, producer-only handoff, call suppression, clearing and reset during analysis, and P4 expiry including timer wraparound. Physical LED output and playback timing require the hardware procedure in MUSIC_EQ_TEST.md.
