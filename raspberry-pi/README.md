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
