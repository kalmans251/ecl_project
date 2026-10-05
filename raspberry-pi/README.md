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

## Pi에서 현장 음성 직접 듣기 (PC 서버 불필요)

`tools/voice_listen.py`는 같은 Pi의 기존 TCP 릴레이(127.0.0.1:9100)를
수신해 libcodec2로 디코딩합니다. PLC UART는 main.py만 열며, 재생은 별도
프로세스에서 수행하므로 PLC 수신 스레드에 디코딩/사운드 출력을 추가하지 않습니다.
Pi에 USB 스피커 또는 USB 사운드카드와 스피커를 연결하세요.

설치 (raspberry-pi 디렉터리):
```bash
sudo apt update
sudo apt install libcodec2-dev libportaudio2 python3-venv
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-playback.txt
python tools/voice_listen.py --list-devices
```

터미널 1 (기존 main.py가 실행 중이면 중복 실행하지 말고 그 콘솔 사용):
```bash
source .venv/bin/activate
python main.py --port /dev/ttyAMA2 --voice-host 127.0.0.1
```
현장 비상 호출을 연결한 뒤 Pi 콘솔에서 `ptt 1 off`로 FIELD_TX를 확인합니다.
`--disable-voice-relay`는 사용하지 않습니다. 외부 PC 접속도 필요하면 기존
`--voice-host` 설정을 유지할 수 있습니다.

터미널 2 (동일 raspberry-pi 디렉터리):
```bash
source .venv/bin/activate
python tools/voice_listen.py --railing 1
```
출력 장치가 틀리면 장치 목록의 출력 가능한 번호를 선택하세요. 예:
```bash
python tools/voice_listen.py --railing 1 --device 2 --buffer-ms 600
```

첫 소리는 최소 600ms 분량을 모은 뒤 나옵니다(8프레임 패킷 4개는 640ms).
원본 PCM은 8kHz·모노·16비트입니다. 기본 출력은 USB 장치 호환성을 위해
샘플 반복으로 48kHz로 변환하며 음질을 높이는 처리는 아닙니다.
장치가 지원하면 `--rate 8000` 또는 `--rate 16000`을 사용할 수 있습니다.

5초마다 통계를 출력합니다:
- `packets`: 선택 레일의 수신 패킷 수
- `missing_packets`: 16비트 시퀀스 기준 누락 추정(PTT 전환/송신 재시작과 구분해 해석)
- `buffer_underflows`: 재생 시작 후 PCM이 부족해 무음 출력·재버퍼링한 횟수
- `device_underflows`: PortAudio가 보고한 출력 부족 횟수
- `overflow_samples`: 지연이 2초를 넘지 않도록 버린 출력 샘플 수
- `buffer_ms`: 현재 대기 PCM 분량, `resets`: 긴 공백/큰 시퀀스 차이로 재초기화한 횟수

누락은 제한된 무음으로 채우며 원래 음성을 복원하지는 않습니다. 버퍼 부족이면
`--buffer-ms 800`으로 비교해볼 수 있지만 전송 누락 자체를 해결하지는 못합니다.
5분 연속 FIELD_TX에서 누락/부족/넘침 수치가 증가하는지와 실제 소리를 함께
확인한 뒤 PTT on/off도 시험하세요. 통화가 끝나면 남은 버퍼가 짧게 재생될 수
있습니다. Ctrl+C로 종료합니다. Pi 실물의 출력 장치와 음질은 현장 검증이 필요합니다.

## Pi → WROOM 스피커 (마이크 또는 테스트 톤)

Pi의 3.5mm 잭은 출력 전용입니다. 마이크 송신에는 USB 마이크/USB 사운드카드
입력 등이 필요합니다. 마이크가 없어도 테스트 톤으로 역방향 경로를 시험할 수 있습니다.

먼저 새 WROOM 펌웨어를 빌드/플래시하세요. P4/S3 펌웨어 변경은 없습니다.
WROOM I2S 출력은 기존 설정 BCLK=GPIO32, LRCK=GPIO33, DOUT=GPIO27이며
기존 I2S DAC/앰프와 스피커가 필요합니다. 일반 아날로그 앰프에는 I2S DAC를
거쳐 연결해야 합니다. 이 코드는 WROOM GPIO에서 스피커를 직접 구동하지 않습니다.

Pi에서 기존 venv를 활성화하고 `requirements-playback.txt`를 설치합니다.
기존 main.py 한 개만 실행하고 현장 호출을 연결합니다. Pi 콘솔에서:
```text
ptt 1 on
```
`[CALL] DIRECTION rail=1 CONTROL_TX`와 `PTT ON`을 확인한 뒤 다른 터미널에서:
```bash
source .venv/bin/activate
python tools/voice_send.py --railing 1 --tone --seconds 10
```
440Hz 테스트 톤을 Codec2로 인코딩합니다. Codec2는 음성 코덱이므로 톤이 원음과
똑같이 들리지는 않습니다. Pi의 `CONTROL Codec2 -> PLC` 로그와 WROOM의
`Codec2 PLAY` 로그, 실제 스피커 출력을 함께 확인하세요. 처음 약 480ms의
패킷을 모읍니다. 큐 부족/누락/가득 참/I2S 실패는 WROOM 로그에 표시합니다.

마이크 장치 확인과 송신:
```bash
python tools/voice_send.py --list-devices
python tools/voice_send.py --railing 1 --device 2 --seconds 30
```
`--device 2`는 예시이며 반드시 입력 채널이 있는 실제 장치 번호로 바꿉니다.
기본 캡처는 48kHz·모노이며 20ms 단위의 간단한 평균 다운샘플링으로 8kHz를
만듭니다. 입력 장치가 지원하면 `--rate 8000`으로 원래 샘플률을 사용할 수
있습니다. 8프레임/160ms마다 전송합니다. `sent_packets`는 TCP 전달 수이며
WROOM 수신·재생 성공을 보장하는 수치가 아닙니다. 캡처 부족/큐 버림도 표시합니다.

Ctrl+C 또는 `--seconds` 종료는 송신만 중지하며 PTT를 바꾸지 않습니다.
송신 종료 뒤 main.py 콘솔에서 `ptt 1 off`로 현장 마이크 방향에 복귀하세요.
송신 프로그램을 다시 실행할 때는 `ptt off`→`ptt on`으로 WROOM 세션 시퀀스를
초기화하세요. 한 레일에는 송신 클라이언트를 하나만 사용합니다.

WROOM은 통화 중 음악/비상음 제어를 거절하며, CONTROL_TX 재생 시 기존 음악을
일시 정지하고 I2S 출력을 전용 태스크가 사용합니다. 방향 변경/통화 종료 시
대기 음성을 폐기하고 출력을 반환합니다. 음악 재개는 기존 P4 제어 흐름을 따릅니다.
Pi 마이크 소리·WROOM 출력·반복 PTT 전환은 실물에서 검증해야 합니다.


## Integrated Pi USB microphone and AUX test

Use one `main.py` process for serial ownership, PTT and local audio. Stop older
`voice_send.py` / `voice_listen.py` processes first. Install the same optional
playback dependencies used by those tools:

```bash
sudo apt install libcodec2-dev libportaudio2
python -m pip install -r requirements-playback.txt
python main.py --list-audio-devices
python main.py --local-audio --audio-railing 1 --mic-device 1 --speaker-device 0
```

Device indices are examples: choose the current **GM20U USB Audio input** and
**bcm2835 Headphones output** from the list. Output 0 was the headphones device
in the Pi test; indices may change after USB reconnection. An output name can
also be used: `--speaker-device "bcm2835 Headphones"` (the local-mode default).
Connect the AUX powered speaker/amp as in the earlier Pi listening test.
Use the project's active virtual environment for pip and main.py.

After emergency ACK establishes a call:

- `ptt 1 on`: after P4 confirmation, USB microphone PCM is encoded as Codec2 and
  sent to WROOM. AUX playback is muted and its stale buffer cleared.
- `ptt 1 off`: stop outbound voice before transmitting the command; after P4
  confirmation, FIELD Codec2 is decoded locally and played through Pi AUX.
- `hangup 1`: pause voice, request STOP and wait/retry for P4 CALL_ENDED.
- `voice-status`: inspect local sent/received counts, input/queue drops, missing
  packets, buffer/device underflows, local audio error and `control_paused`.
- `quit`: close both PortAudio streams, join workers and close relay/UART.

Only the selected railing uses the local mic/AUX endpoint. Calls and PTT state
still come from the existing P4 protocol. Local capture callbacks never write
PLC; FIELD decoding never runs in the PLC reader. Buffers are bounded and old
samples are invalidated by PTT/state tokens. All CONTROL sources are paused
through direction/hangup confirmation, with 100ms modem turnaround after the
last voice write. This margin needs validation on the actual PLC modem.
If confirmation fails, voice remains paused; retry `ptt` or `hangup` and inspect
P4/grant logs. The local endpoint reserves the selected rail's CONTROL source,
so a forgotten external mic sender cannot mix with it. Do not run separate voice
tools in local mode.

For a later server/monitoring deployment, omit `--local-audio`. The TCP relay
continues accepting **already encoded Codec2 CONTROL packets**, forwarding their
compressed data to PLC without PCM conversion. FIELD packets are always offered
to TCP listeners in the original Codec2 network format even when local AUX
playback is enabled. Server session/PTT orchestration must invoke the same
pause/confirmation flow; a remote PTT command API is not introduced here.

Hardware validation: talk in each direction for 2–3 minutes, switch PTT on/off
10 times while speaking, and hang up during transmission. Check that control
remains responsive, no old audio resumes after switching, AUX is silent during
CONTROL_TX, and `voice-status` counters agree with audible playback. Host tests
exercise real Codec2 with fake audio devices and a fake PLC, not physical audio
or modem timing.


## Device controls before monitoring integration

These commands use the same `main.py` console, including `--local-audio` mode.
Update Pi and flash P4 + WROOM from this change for the new volume protocol.
No S3 firmware change is needed. Existing local default volumes are not edited.

```text
query 1 p4
query 1 wroom
query 1 s3
power 1 ac
power 1 battery
power 1 on
power 1 off
projector 1 on
projector 1 off
led 1 on
led 1 basic
led 1 weather rain
led 1 music
led 1 off
music 1 mode sequential
music 1 mode shuffle
music 1 mode age
music 1 start
music 1 pause
music 1 resume
music 1 next
music 1 stop
volume 1 10
sleep 1 on
sleep 1 off
detection 1 radar
detection 1 cctv
```

`power ac|battery` sends SET then START. `power on|off` applies/stops the
currently configured mode; P4 AUTO power control is not implemented, so select
AC or battery first. Weather choices are clear/cloudy/rain/snow. LED MUSIC mode
and `music start` are distinct controls; choose LED MUSIC for music playback
policy. Age playback and CCTV detection need their existing analysis input;
selecting them does not provide a Pi-local CCTV/age implementation.
Sleep uses the existing firmware policy/timeout (currently 10 seconds); this
change does not alter wake logic or finish-at-track-end behavior.

`volume 1 10` sets shared WROOM music/voice output gain to 10% via P4 using
MUSIC/SET payload `[0x03, percent]`. Valid range is 0..100, held in RAM until
reboot. Emergency alert gain still uses its existing separate configuration.
The new setting does not alter source-code volume defaults. Test requests while
idle: all general commands, including UART ping/status queries, are rejected
while any cached call/emergency is active on the shared PLC bus or PTT
confirmation is unresolved. They are discarded rather than saved for later.
P4 also rejects general Pi commands during its own active call.

`status` reads the existing Pi cache without UART traffic. `query` requests a
live SYSTEM response, printed as `[DEVICE STATUS]`. P4's existing SYSTEM reply
is only an alive byte; WROOM reports alive/SD mounted/music state/railing ID;
other payloads are shown raw. These are not a full settings snapshot.
General setters have no firmware ACK: `Request sent` confirms serial transmission,
not physical application. Verify corresponding device logs and actual outputs.

Suggested hardware test, outside a call: query the devices; set `volume 1 10`,
`led 1 music`, sequential mode and start/pause/resume/next/stop music; test LED
weather/basic and projector; test sleep/radar wake. During a call, try `led 1
basic` and verify rejection while PTT still responds. Test configured power
selection as a separate step. EQ data generation remains the next integration
work item.
