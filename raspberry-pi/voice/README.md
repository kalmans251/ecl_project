# Codec2 relay — design checkpoint

Pi does **not** encode or decode Codec2. S3 encodes FIELD_TX; the monitoring PC decodes FIELD_TX and encodes CONTROL_TX; WROOM decodes CONTROL_TX.

This branch is a protocol-design checkpoint only. Do not merge or deploy as a functioning voice relay yet.

Existing repository voice/packet.py and voice/relay.py already contain a richer network format and relay implementation. The packet contract must be reconciled with those existing modules and the P4/S3/WROOM protocol before modifying the runtime.

Proposed on-PLC AUDIO/DATA packet format:
- byte 0: 0x02 compressed audio
- byte 1: Codec2 mode identifier (to be aligned with existing Codec2Mode)
- byte 2: direction FIELD_TX or CONTROL_TX
- bytes 3-4: sequence, big-endian
- byte 5: number of compressed frames
- byte 6: bytes per compressed frame
- remaining: compressed frames

**Important correction:** Codec2 mode 2400 normally uses 48 bits per **40 ms** frame, i.e. 6 bytes, not 20 ms. Eight frames represent 320 ms, not 160 ms. Latency and PLC capacity need evaluation before choosing aggregation size.

Next integration:
1. Reuse the existing voice/packet.py network framing and voice/relay.py rather than introduce an incompatible packet format.
2. Check P4 forwarding and voice priority against 9600-baud half-duplex PLC.
3. Wire Pi's call-state gating and monitoring transport.
4. Implement S3 encode and WROOM decode.
5. Verify PTT state transitions and end-to-end audio on hardware.
