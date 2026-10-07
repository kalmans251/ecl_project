# CCTV event console tests

Only Raspberry Pi changes. Keep P4/WROOM/S3 firmware unchanged.
These commands inject analysis results; they do not process video or connect a server.
Stop any call/emergency before testing. Transmission messages do not confirm P4 application.

## Setup
```text
detection 1 cctv
music 1 mode age
led 1 music
music 1 start
sleep 1 on
```

Confirm setup on P4/WROOM logs. Mode switching resets the activity timer.
Use a fresh 32-bit event sequence for each new person.

## Detection and matching age
```text
cctv 1 enter 100
cctv 1 age 100 20
```
P4 should log CCTV NEW seq=100 and AGE -> GROUP 2; WROOM should select its
20s group. Setting the group does not interrupt a currently playing track.
Use music 1 next to hear the selected group while active.

Resend the same enter/age: P4 should log duplicates without increasing counts.
In radar mode CCTV events are ignored.

## Sleep wake
Wait until P4 reports SLEEPING (in music mode it may wait for the current track
to finish after the 10-second idle interval). Send a fresh enter, then promptly
the matching age. P4 should wait for age then wake with the selected group.

```text
cctv 1 enter 101
cctv 1 age 101 keep
```
keep represents failed age classification and preserves the group.
For a timeout test send only cctv 1 enter 102 while sleeping: P4 wakes after
its 2-second age fallback. Pi does not automatically send keep.

## Contract
Pi -> P4, DETECTION=0x09, DATA=0x23.
enter: 0x01 + unsigned 32-bit big-endian sequence.
age: 0x02 + same sequence + age code (10/20/30/40 -> 1/2/3/4; keep -> 255).
Sequence input accepts decimal or 0x hexadecimal, 0..4294967295.
This is a cumulative new-person event, not current occupancy or coordinates.
No automatic retries, sequence generation or application acknowledgments are added.
