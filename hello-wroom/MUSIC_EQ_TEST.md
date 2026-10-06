# Music EQ hardware test

For the asynchronous EQ update, flash WROOM only if the previous eight-band P4 change (PR #18) is already installed. Pi, P4 and S3 need no additional changes.

WROOM analyzes the stereo PCM already decoded for music, automatically scales the display by the recent music peak, independently of speaker volume, and sends eight levels (0–255) to P4 about ten times per second. This is UART LED/DATA traffic, not PLC traffic. Playback PCM is unchanged. The music task copies at most one MP3 frame into a mono mailbox; a priority-1 EQ task performs FFT and logging. New PCM replaces unprocessed PCM rather than delaying playback. A full router queue drops EQ updates without waiting. P4 blanks stale levels after 500 ms and clears them while music is stopped or a call is active.

| Band | Frequency range (Hz) |
| --- | --- |
| 1 | 0–125 (DC excluded) |
| 2 | 125–250 |
| 3 | 250–500 |
| 4 | 500–1000 |
| 5 | 1000–2000 |
| 6 | 2000–4000 |
| 7 | 4000–6000 |
| 8 | 6000–8000 |

Start the existing Pi console and run:

```text
volume 1 10
led 1 music
music 1 mode sequential
music 1 start
```

Expect moving bars and a WROOM `MUSIC_EQ` log approximately every five seconds, including `sent`, `dropped`, `overwritten`, `analysis_max_us`, and eight levels. Listen for playback continuity for at least ten minutes. Record the maximum analysis time and dropped count; host tests cannot prove the hardware timing budget.

Test `music 1 pause`, `music 1 resume`, `music 1 next`, and `music 1 stop`. Bars should clear on pause/stop and follow the next track. Test volume 0: the speaker must be silent while bars continue to follow the music. Then restore a comfortable volume. Quiet tracks should still reach upper rows; genuine silent PCM should bring bars down. Switch LED basic/weather modes and return to music; old bars must not remain.

With the existing local audio command, establish a call and toggle `ptt 1 on` / `ptt 1 off`. Confirm both voice directions still work and music EQ traffic stops during the call. After ending the call, verify the normal music resume behavior and new EQ updates. Keep the confirmed DAC SCK-to-GND wiring.

Analysis uses a 256-point Hann-window FFT at a display analysis rate of 16 kHz and about 3 KB of analyzer state plus two mono mailboxes (about 4.6 KB total). The worker allocates a 3 KB stack at initialization; no per-frame allocation is used. The worker owns one heap workspace containing the analyzer and both mailboxes; call START returns that workspace, while STOP allows it to be recreated lazily. Its stack remains allocated. The fractional box decimator is intended for a visual display, not a precision spectrum instrument. Stereo channels are averaged. The nominal EQ traffic is 18 bytes × 10/s on the existing 115200-baud UART (about 1.6% with serial framing).

Compare the same track for ten minutes at a comfortable volume. Check pause/resume/next and repeated call/PTT transitions. `overwritten` may increase when EQ falls behind; this indicates intentionally skipped display data, not dropped speaker PCM. A worker allocation failure disables EQ and leaves music available. Record the existing decoder heap and voice stack diagnostics after starting a call to verify the additional worker memory on the board. Separating FFT removes that work from the playback task, but an audible dropout from SD, I2S, scheduling or hardware requires further diagnosis.
