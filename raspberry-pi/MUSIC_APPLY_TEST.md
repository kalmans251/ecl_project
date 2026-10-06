# Music STOP and volume application confirmation

Update Raspberry Pi, ESP32-P4 and ESP32-WROOM together. ESP32-S3 needs no change.
Other general controls still report transmission only.

Run the existing console and, outside a call/emergency, try:

```
volume 1 20
volume 1 0
music 1 stop
music 1 stop
```

Volume and STOP should print `Applied rail=1: ... (WROOM confirmed)`.
Test STOP both during playback and while idle. Volume 0 should mute output;
restore a comfortable volume afterwards. Calls/emergencies block general controls.
A rejected command or device execution failure is distinct from a timeout.
A timeout means the application state is unknown: inspect the device before retrying.
The console does not automatically replay commands.

## Wire contract

Service MUSIC, command APPLY (0x28): big-endian request ID (4 bytes), original
command (1 byte), original payload. STOP has 5 bytes. Volume has 7 bytes:
`id[4], SET, 3, percent` (0..100).

APPLY_RESULT (0x29) has 7 bytes: `id[4], original command, status, detail`.
Status 0 means applied, 1 rejected, 2 execution failed. Successful STOP detail is
IDLE (0); successful volume detail is the read-back percentage.

P4 validates policy and forwards requests to WROOM. WROOM confirms volume after
setting and reading it back. STOP is acknowledged by the music task after playback
cleanup and I2S deinitialization, or after it consumes STOP while already idle.
P4 forwards WROOM results preserving the source. Pi requires matching rail, request
ID, operation and applied detail, and accepts success only from WROOM. P4 may reject.
Late replies cannot confirm another request. Default reply timeout is 3 seconds.
This confirms software application, not measured acoustic output.
