# Codec2 relay contract (prototype)

Pi never encodes or decodes Codec2. PC encodes CONTROL_TX and decodes FIELD_TX.

AUDIO / DATA payload:
- byte 0: 0x02 compressed audio
- byte 1: 0x01 Codec2 mode 2400
- bytes 2-3: sequence, big-endian
- byte 4: number of frames (1..8)
- byte 5: bytes per frame (6)
- remaining: concatenated compressed Codec2 frames

This is a proposed packet contract, not yet integrated with S3 or WROOM firmware.
The field uplink is P4 -> Pi. The control downlink is Pi -> WROOM
through the P4 router.

The transport from Pi to the Spring Boot monitoring system is not implemented.
Do not stream until PLC bus scheduling and PTT priority are implemented.
