# Music information: first implementation stage

Update Pi, P4 and WROOM together. S3 does not change. This stage adds read-only
catalog and actual player queries; track selection, total duration, seeking and
monitoring UI integration remain subsequent stages. No automatic music polling.

Run manual hardware_test.py with the usual port/local audio options, then:

```
music 1 list
music 1 list default
music 1 list 20
led 1 music
music 1 start
music 1 status
wait 5
music 1 status
music 1 pause
music 1 status
wait 5
music 1 status
music 1 resume
music 1 next
music 1 status
music 1 stop
music 1 status
```

Check filename matches the audible song, position advances during playback,
freezes once paused, and resets on the next track. `idle` retains the last file
and position; it does not mean that file is still playing. `duration_ms: null`
means unknown, not zero. Position counts PCM submitted to I2S; hardware buffering
can make it slightly ahead of sound. File names are displayed as UTF-8, replacing
invalid bytes. Indices are zero-based and only valid for the returned catalog
version. Catalog count limit is the existing firmware limit (32 per group).

Queries are blocked during calls/emergencies (same policy as general controls).
A full catalog is fetched one track per PLC transaction. At 9600 baud, a large
catalog may take many seconds; this is deliberately not a continuous stream.
Do not remove/replace the SD card while playing. A changed version or incomplete
response fails the whole listing rather than displaying a partial list.

## Wire contract

SERVICE_MUSIC, CMD_APPLY: request_id[4], operation[1], arguments.
All numbers are unsigned big-endian. P4 validates and forwards to WROOM;
CMD_APPLY_RESULT preserves WROOM source and echoes request_id, operation, status.
Only status=0 from WROOM is a successful read; P4 policy success is not accepted.

- 0x30 MUSIC_INFO, no arguments: state[1], position_ms[4], name_length[1], name.
- 0x31 MUSIC_CATALOG, no arguments: version[4], five group counts[2] each.
- 0x32 MUSIC_TRACK: version[4], group[1], index[2]. Reply detail echoes those
  seven bytes then name_length[1], name. Groups 0/default,1/10,2/20,3/30,4/40.
- Failed/rejected results use the existing 7-byte envelope.

Longest successful result: 6-byte envelope + 8-byte track metadata + 95-byte
filename + 10-byte frame overhead = 119 bytes (below 128 bytes).
Late replies, other rails, wrong source/token/op and changed catalog identities
must not satisfy a pending request. CRC validation remains mandatory.
