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
