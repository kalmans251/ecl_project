# S3 microphone and Codec2 FIELD_TX

The S3 captures INMP441 audio and encodes Codec2 2400. Pi and P4 remain
packet relays. WROOM decoding and the control-center PC audio application
are separate, unfinished parts of the end-to-end voice path.

## Build and upload

```bash
cd esp32-s3-arduino
pio run
pio run -t upload --upload-port /dev/ttyUSB0
pio device monitor --port /dev/ttyUSB0 --baud 115200
```

Use the board's actual serial port. PlatformIO pins Espressif32 7.0.1
(Arduino ESP32 2.0.17) and the Codec2 dependency to an exact source commit.
Only Codec2 mode 2400 is enabled. Its upstream library is LGPL-2.1-or-later;
the dependency retains its license and source headers.

## INMP441 wiring

| INMP441 | S3 |
| --- | --- |
| VDD | 3.3 V |
| GND | GND |
| WS | GPIO 7 |
| SCK | GPIO 6 |
| SD | GPIO 5 |
| L/R | GND for the default LEFT channel |

`include/board_config.h` contains the pins, `MIC_USE_RIGHT_CHANNEL` and
`MIC_GAIN` (default 4). If L/R is connected to 3.3 V, select RIGHT. Reduce
gain if `clip` rises; check wiring/channel selection if `peak` stays zero.

## Operation

1. Start the Pi program and its TCP voice relay.
2. Connect `raspberry-pi/tools/voice_test_client.py <PI_IP>` on the PC.
3. Trigger the physical emergency button and run `ack 1` on the Pi.
4. P4 starts WROOM/S3 audio sessions in FIELD_TX. S3 then starts capture.
5. Expect `[MIC] FIELD_TX capture started` and increasing `[MIC] sent`.
   The PC test client should print `FIELD RX rail=1 ... frames=8 bytes=48`.
6. `ptt 1 on` stops capture and invalidates partial/queued FIELD_TX audio.
   `ptt 1 off` creates a new encoder and resumes capture.
7. `hangup 1` stops capture. BLE loss also stops the S3 session locally;
   end/restart the call through P4 after reconnecting.

The test client prints packet reception; it does **not** play sound.
`sent` means the packet was submitted to BLE, not that PLC or PC acknowledged it.

Capture uses 8 kHz, 32-bit I2S slots on the selected channel. Each 160-sample
PCM frame becomes 6 Codec2 bytes. Eight frames form a 48-byte/160-ms packet
using the existing 7-byte audio metadata and 10-byte protocol overhead.
Encoding runs on a 16-KiB FreeRTOS worker stack. A two-packet queue feeds
BLE from the Arduino loop. Full queues and old packets are dropped to bound
latency. Generation changes invalidate queued audio on PTT/stop/start.
S3 suppresses radar detail/new-person transmissions during a call, while
still draining the radar UARTs and checking the physical emergency button.
BLE notifications are split according to the negotiated MTU.

Every five seconds `[MIC]` reports peak PCM level, clipped samples, dropped
packets and the maximum encoding time. Confirm `encode_max_us` stays below
20000 on the actual S3. Packet gaps, audio quality, DMA overrun and PLC
direction-turnaround timing still require physical testing. P4 bus arbitration,
control acknowledgements and reconnect state recovery are separate work.
