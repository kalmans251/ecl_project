# Music information: first implementation stage

Update Pi, P4 and WROOM together. S3 does not change. Stages 1 and 2 add catalog/player queries and selected-track playback.
Total duration, seeking and monitoring UI integration remain subsequent stages. No automatic music polling.

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

## Stage 2: select a displayed track

Pi, P4 and WROOM must all be updated. In the same running console:

```
led 1 music
music 1 start
music 1 list
music 1 play default 0
music 1 status
music 1 play 20 2
music 1 status
```

Use only indices actually returned by the list (zero-based). The example `20 2`
requires at least three songs in that group. A successful list is cached per rail
in this console process. A new/failed list invalidates the previous selection
cache; a group-only list authorizes selecting only its displayed tracks. After
restarting the console, list again. Playback never silently refreshes the version
and selects the same index from a changed catalog.

P4 requires an enabled music session, MUSIC LED mode, no sleep and no pause
reason. Calls/emergencies reject selection at both Pi/P4 and WROOM. Use
`music 1 resume` if user-paused. This command changes one track; subsequent NEXT
and natural-end selection use the existing sequential/shuffle/age policy, not an
implicit new mode. It does not force wake or clear pause reasons.

CMD_MUSIC_PLAY=0x33 uses APPLY arguments version[4], group[1], index[2]. WROOM
validates these against its catalog and queues the file path through the existing
player. The player replies only after first successful PCM write, echoing
state=1 and the seven-byte selection identity in the APPLY_RESULT detail (14-byte
payload total). Queue acceptance is not a playback confirmation. Failures before
PCM produce failure; a timeout leaves application unknown and is not retried.

Check stale-version rejection (rescan/change SD while stopped, then select from
old list), non-existent index rejection, and switching while already playing.
Also repeat call/return and sleep/wake regression tests after selecting a track.
Total duration, seeking and monitoring UI integration remain later stages.
