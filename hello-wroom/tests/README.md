## Required CI suite

Run the same entry point as the `wroom-host-tests` GitHub Actions job (Linux, Python 3, Git and GCC required):

```sh
python hello-wroom/tests/run_host_tests.py --build-dir "$(mktemp -d)"
```

The runner reads `GIT_REPOSITORY` and the full `GIT_TAG` from the firmware's
`components/codec2/CMakeLists.txt`, fetches and verifies that exact commit, and
builds a fresh shared library from the same `src/*.c` files. It uses the firmware's
2400-only mode definitions and single-precision constants. No distribution
Codec2 package or system-library fallback is used. The build directory must not
already contain a `source` checkout; dependencies are intentionally not cached.

The runner sets `ECL_TEST_CODEC2_SRC` and `ECL_TEST_CODEC2_LIB` before discovering
all WROOM tests. Missing required worker/decoder/failure tests, any skip, dependency
fetch/build failures, C compilation failures and failed assertions fail the job.
Direct unittest invocation in CI (or with `ECL_REQUIRE_CODEC2=1`) also fails when
the Codec2 paths are absent. Local direct invocation without those variables may
skip the two dependency-requiring tests; use the runner for complete verification.

Real playback encodes a tone, decodes it through `voice_decoder.c` and the actual
worker, checks that nonzero decoded PCM reaches `audio_output_write` unchanged
apart from the expected sample repetition/stereo conversion, and checks eight
20 ms output blocks per session. Decoder equivalence checks exactly 200 frames
(64,000 bytes) of nonzero PCM against the full constructor. Existing DMA/decoder
failure, retry, queue, audio-output and music tests remain part of the suite.

These are host software checks. RTOS queues, I2S and DMA drivers are substitutes;
passing does not establish ESP32 heap/stack margin, real scheduling, DAC/amp
operation, speaker loudness, noise, or uninterrupted physical playback. Those
require the board procedures below.

## Individual tests and hardware procedure

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

Voice DMA uses an explicit 4-descriptor × 160-stereo-frame profile at 16 kHz (2560 PCM bytes, 40 ms). Normal music/emergency initialization keeps the IDF defaults. The output test checks switching back to the normal profile, reuse within one profile and failed-init cleanup. Worker failure tests inject DMA and decoder failure, drain multiple packets without repeated initialization, then toggle PTT and verify a new attempt.

Hardware: flash WROOM, start music, then Pi `call 1`, `ptt 1 on`, `ptt 1 off`, `hangup 1`. Expect voice I2S log `dma=4 x 160` and `Codec2 playback ... ready`. After voice output releases, the music I2S log should use `dma=6 x 240` for ESP-IDF 6.0.2. Confirm actual voice continuity and music restoration through several cycles, including a call with no music loaded. The reduced DMA budget must be validated on the board. Initialization failure now logs once per PTT generation; use PTT off/on to retry after correcting memory pressure. Host mocks cannot establish real DMA heap availability.

EQ workspace is now allocated by the EQ worker and returned on call START. The controller waits for release completion before returning from voice_session_start; PCM producers never allocate or free it. The persistent EQ task retains its 3 KB stack, but the analyzer and two mono mailboxes (about 8 KB) are freed for voice playback. STOP re-enables lazy allocation. Allocation failure skips EQ and is retried on the next reset/resume rather than every frame. Transport tests check lifetime, release/reallocation, allocation failure, and producer ownership.

After flashing WROOM, run Pi `call 1` then `ptt 1 on`. If music had allocated EQ state, expect `MUSIC_EQ: Released EQ memory for call: ... bytes`, then a higher decoder-before heap diagnostic, `dma=4 x 160`, `Codec2 playback ... ready` and `Codec2 PLAY`. Repeat PTT changes and hangup; verify music and its EQ return without clicks or lost state. Also call directly from boot, with no music played. Failures now explicitly distinguish `Voice I2S DMA initialization failed`, `Codec2 decoder allocation failed`, and `Codec2 decoder format mismatch`. Real board memory and audio continuity remain hardware checks.


### PTT output preparation

`voice_session.c` now prepares the voice DMA profile and Codec2 decoder on
CONTROL_TX, before receiving audio. The first packet still starts the bounded
600 ms jitter-buffer wait. Waiting for that first packet does not count as an
underflow. Initialization/ownership failures are latched for that generation;
a fresh PTT direction transition is required to retry.

`voice_session_output_state()` exposes IDLE/PREPARING/READY/STOPPING/FAILED
locally. This remains a local output state accessor. The endpoint report combines it
with the current session/request, and P4 waits for both endpoint reports.
Endpoint acknowledgements and P4 aggregation are now connected; see
[`CALL_READINESS.md`](../../CALL_READINESS.md).

Host tests cover preparation without packets, release before any playback,
failed DMA/decoder initialization, first-packet playback with deterministic
PCM, and music-rate restoration. Real Codec2 integration tests additionally
require `ECL_TEST_CODEC2_SRC` and the Codec2 library. Hardware validation is
intentionally deferred.
