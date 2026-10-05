# Control voice playback

Build with the project's ESP-IDF v6.0.2 / ESP32 environment:

```bash
cd hello-wroom
idf.py build
idf.py -p YOUR_WROOM_PORT flash monitor
```

The `codec2` component downloads Meshtastic's LGPL-2.1-or-later vocoder at
`3e347e0b70fc72af9357fbbd32b10a125321d6c5` during initial CMake configure.
Git/network access is required then. The same revision is used by the S3 encoder.
The dependency retains its source/license in the build directory; distribution
must retain the applicable Codec2 license/source obligations.

Stereo I2S uses the existing GPIO32 BCLK / GPIO33 LRCK / GPIO27 DOUT pins.
Codec2 2400 mono PCM is duplicated to both channels at 8kHz with existing volume
settings. Connect the existing I2S DAC/amplifier and powered speaker circuit.

The controller only validates/enqueues packets. A dedicated task prebuffers
three packets (normally 480ms), decodes six-byte frames and writes 20ms PCM blocks.
The compressed queue is bounded to 12 packets. Session generations discard
old audio on PTT change/stop. Identical PTT retries do not flush valid audio.
Output ownership blocks music/alert tasks from reconfiguring or writing I2S while
voice owns it. Missing packets are reported and bounded silence may be inserted;
original missing speech cannot be recovered. Queue/I2S errors are logged.

See raspberry-pi/README.md for local Pi microphone and no-microphone tone tests.
Host check (with libcodec2 installed), from repository root:
`python -m unittest discover -s hello-wroom/tests -v`.
This compiles the actual session/worker C with RTOS/audio substitutes; hardware
I2S output and real-time behavior still require board testing.

## Packets arrive but are rejected

`Rejected AUDIO DATA len=55` alone does not identify the cause. New diagnostics
print metadata, session active/direction, or missing playback task/queue.
After WROOM reboot, its call state is lost while P4/Pi may still consider the
call active. A valid AUDIO direction command from P4 now restores that local
session. Ordinary data packets and non-P4 direction commands do not start calls.
P4 itself checks that a call is active before generating direction commands.
Repeat `ptt on` after reboot to synchronize; repeated same-direction commands
keep an already active audio queue intact. Initialization/allocation failures
still require inspecting the full WROOM startup log.
