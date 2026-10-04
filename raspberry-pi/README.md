# Raspberry Pi PLC Controller

Raspberry Pi side of the smart-railing communication stack.

Current scope:

- PLC UART: `/dev/ttyAMA2`, 9600 baud, 8N1
- application protocol compatible with the P4 firmware
- CRC-16/CCITT-FALSE
- streaming frame parser with resynchronization
- per-railing in-memory state cache
- emergency START/STOP receive path
- control-center emergency ACK transmit path
- simple interactive test console

## Architecture

```text
S3
  <-> BLE
WROOM
  <-> UART
P4
  <-> PLC 9600
Raspberry Pi
```

The Pi is intended to become the bus master, state cache, SQLite owner,
telemetry scheduler and PTT gateway. Spring Boot will be connected after
the Pi-side functions are stable.

## Install

```bash
cd raspberry-pi

python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
```

Make sure the Pi user can access the UART device.

```bash
sudo usermod -aG dialout $USER
```

Log out and back in after changing group membership.

## Run

```bash
python main.py --port /dev/ttyAMA2
```

For verbose protocol logs:

```bash
python main.py --port /dev/ttyAMA2 --log-level DEBUG
```

## Interactive commands

```text
status
status 1
ping 1
ack 1
ptt 1 on
ptt 1 off
hangup 1
quit
```

### Emergency flow

Field button long press:

```text
S3 -> P4 -> Pi
SERVICE_EMERGENCY / CMD_START
payload[0]    = source
payload[1..4] = emergency_seq (big-endian)
```

Field-side cancel:

```text
S3 -> P4 -> Pi
SERVICE_EMERGENCY / CMD_STOP
payload[0]    = source
payload[1..4] = same emergency_seq
```

Control-center ACK:

```text
Pi -> P4
SERVICE_EMERGENCY / CMD_SET
payload[0]    = EMERGENCY_ACTION_ACK
payload[1..4] = active emergency_seq
```

The P4 then stops the WROOM emergency alert and starts the emergency call
in FIELD_TX mode.

## Protocol tests

```bash
cd raspberry-pi
python -m unittest discover -s tests -v
```

No physical UART is required for these protocol tests.

## Important PLC note

The current Pi implementation serializes all Pi-originated writes.
When multiple P4 nodes share the same half-duplex PLC bus, bus arbitration
for spontaneous node-originated events must be finalized before scaling
to many railings. The first target is one-railing end-to-end validation.


## Emergency ACK / call state synchronization

After the Pi sends `ack <railing_id>`, P4 now reports the result back to the Pi.

Expected sequence:

```text
[EMERGENCY] START rail=1 source=BUTTON seq=...
ACK sent rail=1 seq=...
[CALL] STARTED rail=1 origin=EMERGENCY direction=FIELD_TX
[EMERGENCY] ACK CONFIRMED rail=1 seq=...
```

The exact order of the last two lines can be close together because both are queued by P4.

`status 1` should then show:

- `emergency.active = false`
- `call.active = true`
- `call.origin = 1` (EMERGENCY)
- `call.direction = 1` (FIELD_TX)

P4 also sends call direction-change and call-ended events so the Pi cache can remain authoritative for the later Spring Boot monitoring layer.


### PTT control-plane test

The Codec2 audio payload is not implemented yet, but the half-duplex direction control can already be tested.

After an emergency ACK starts a call:

```text
ptt 1 on
```

requests `CONTROL_TX` (control center -> field).

```text
ptt 1 off
```

returns to `FIELD_TX` (field -> control center).

P4 confirms each direction change back to the Pi, so the cached `call.direction` value should change in `status 1`.

To end the call:

```text
hangup 1
```

P4 should report `CALL_ENDED`, after which `status 1` shows `call.active = false`.


## Codec2 packet relay

The Raspberry Pi does **not** encode or decode Codec2 audio.

Codec responsibilities:

```text
FIELD_TX
S3 microphone -> S3 Codec2 encode
 -> WROOM relay -> P4 relay -> PLC
 -> Raspberry Pi packet relay
 -> control-center PC Codec2 decode

CONTROL_TX
control-center PC microphone -> PC Codec2 encode
 -> Raspberry Pi packet relay -> PLC
 -> P4 relay -> WROOM Codec2 decode -> speaker
```

### MCU/PLC audio payload

`SERVICE_AUDIO + CMD_DATA` uses:

```text
[0]      AUDIO_DATA_CODEC2 = 0x02
[1]      CODEC2_MODE_2400  = 0x01
[2]      direction         = 0x01 FIELD_TX / 0x02 CONTROL_TX
[3..4]   packet sequence   = uint16 big-endian
[5]      frame count
[6]      bytes per Codec2 frame
[7..]    concatenated Codec2 data
```

For Codec2 2400:

```text
20 ms per frame
48 bits = 6 bytes per frame
recommended packet = 8 frames
8 x 20 ms = 160 ms
8 x 6 bytes = 48 bytes Codec2 data
```

This keeps one normal application-protocol voice packet small enough for the 9600-baud PLC path.

### Pi <-> control-center TCP format

The Pi listens on TCP port `9100` by default.

Run:

```bash
python main.py \
  --port /dev/ttyAMA2 \
  --log-level DEBUG \
  --voice-host 0.0.0.0 \
  --voice-port 9100
```

The TCP stream uses a separate 12-byte binary envelope:

```text
2 bytes  magic       "RV"
1 byte   version     1
1 byte   railing_id
1 byte   direction
1 byte   codec mode
2 bytes  sequence    big-endian
1 byte   frame count
1 byte   bytes/frame
2 bytes  data length big-endian
N bytes  Codec2 data
```

No PCM conversion occurs in the Pi.

### Current relay validation

The WROOM decoder is not implemented in this PR yet. WROOM validates and counts incoming CONTROL_TX Codec2 packets so the route can be tested before adding the decoder.

After an emergency call is connected:

```text
ack 1
ptt 1 on
```

Then from a PC that can reach the Pi:

```bash
python tools/voice_test_client.py <PI_IP> \
  --railing 1 \
  --send-control \
  --count 10
```

The test client sends dummy 8-frame Codec2-sized packets, not actual audio.

Expected Pi log:

```text
Voice client connected ...
CONTROL Codec2 -> PLC rail=1 ...
```

Expected WROOM log:

```text
VOICE_SESSION: DIRECTION -> CONTROL_TX
VOICE_SESSION: Codec2 RX seq=0 frames=8 bytes=48 packets=1
```

Check Pi relay counters with:

```text
voice-status
```

When S3 Codec2 encoding is implemented, running the test client without `--send-control` will print FIELD_TX packets received from the railing.

### Direction enforcement

The Pi only forwards:

- S3 -> control center while the cached call direction is `FIELD_TX`
- control center -> WROOM while the cached call direction is `CONTROL_TX`

Packets that do not match the active half-duplex direction are dropped.

The TCP relay currently has no authentication or encryption. Bind it only on a trusted LAN/VPN interface until the monitoring-server integration adds authenticated transport.
# PLC 제어 창과 PTT 확인

현장 송신 중 P4는 음성 4패킷마다 제어 창 프레임을 보내고 200ms 동안
PLC 송신을 멈춥니다. Pi는 새 창에서 해당 레일의 PTT/통화 종료 명령을
보냅니다. 음성이 없는 FIELD_TX 상태에서도 주기적으로 창을 제공합니다.
PTT는 P4의 새 방향 변경 응답을 확인해야 성공으로 표시하며 최대 3회 시도합니다.
TCP 음성 전송은 별도 스레드와 최대 2패킷 큐를 사용해 PLC 수신 지연을 줄입니다.

P4와 Pi를 함께 업데이트해야 합니다. 구형 P4에서는 창을 받지 못해 시간
초과됩니다. S3/WROOM은 이번 변경으로 다시 플래시할 필요가 없습니다.

현장 시험:
1. P4를 빌드/플래시하고 Pi 프로그램을 새 코드로 재시작합니다.
2. 레일 1 통화에서 현장 음성이 들어오는 동안 `ptt 1 on`을 입력합니다.
3. `PLC control TX in granted window rail=1 window=200ms`,
   `[CALL] DIRECTION rail=1 CONTROL_TX`, `PTT ON rail=1`을 확인합니다.
4. FIELD 음성 전달이 멈추는지 확인하고 `ptt 1 off`로 현장 송신을 재개합니다.
   20회 반복하고 통화 종료도 시험합니다.
5. 시간 초과/재시도 발생 시 Pi와 P4 로그를 함께 보관합니다.

Pi는 창 수신 후 20ms 대기하고 명령을 전송합니다.
200ms는 수신 실패를 조사하기 위해 늘린 시험값이며 실제 모뎀의 지연으로 검증해야 합니다. P4
`main/board_config.h`의 `PLC_CONTROL_WINDOW_MS`(20~200ms)와
`PLC_VOICE_PACKETS_PER_GRANT`로 조정합니다. 창을 늘리면 음성 처리량도
점검해야 합니다. 여러 P4의 동시 송신을 조정하는 전체 버스 중재는 구현하지
않습니다. 방향 응답 자체가 유실되면 실제 P4 방향과 Pi 상태가 달라질 수
있으며, 확인되지 않은 요청은 성공으로 표시하지 않습니다.

Pi 검사: raspberry-pi 디렉터리에서 `python -m unittest discover -s tests -v`.
P4 호스트 검사: 저장소 루트에서 `python -m unittest discover -s hello-p4/tests -v`.
호스트 검사는 실제 C 스케줄을 모의 UART로 검사하며 ESP-IDF 전체 빌드와
물리 PLC 시험은 별도로 필요합니다.
