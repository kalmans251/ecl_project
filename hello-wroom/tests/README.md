Run host tests against the exact Codec2 revision pinned in components/codec2/CMakeLists.txt:

```sh
ECL_TEST_CODEC2_SRC=/path/to/codec2/src ECL_TEST_CODEC2_LIB=/path/to/pinned-libcodec2.so python -m unittest discover -s hello-wroom/tests -v
```

The decoder test compares 200 frames of PCM byte for byte against codec2_create(2400), using separate processes to keep the library global excitation RNG identical. It injects failure at all five decoder allocations and checks complete cleanup. The worker test runs actual session code with RTOS/I2S substitutes and the real decoder.

WROOM uses decoder-only state because the full Codec2 constructor allocates unused encoder FFT, pitch analysis and input filters. Its internal layout is tied to the pinned Codec2 source: rerun equivalence tests and audit constructor fields when updating that dependency. Always pair voice_decoder_create with voice_decoder_destroy.

Hardware: rebuild and flash WROOM, establish the call, run `ptt 1 on`, then `python tools/voice_send.py --railing 1 --tone --seconds 10` on Pi. Expect `Codec2 PLAY` with no reset. Record the decoder heap diagnostic and playback stack-free diagnostic. Allocation failure should log an error and keep the firmware running. Actual heap availability and audible continuity require hardware verification.
