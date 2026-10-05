# Music EQ hardware test

Flash both WROOM and P4 after applying this change. Pi and S3 do not need changes.

WROOM analyzes the stereo PCM already decoded for music, scales the display by the current output volume, and sends eight levels (0–255) to P4 about ten times per second. This is UART LED/DATA traffic, not PLC traffic. Playback PCM is unchanged. A full router queue drops EQ updates without waiting. P4 blanks stale levels after 500 ms and clears them while music is stopped or a call is active.

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

Expect moving bars and a WROOM `MUSIC_EQ` log approximately every five seconds, including `sent`, `dropped`, `analysis_max_us`, and eight levels. Listen for playback continuity for at least ten minutes. Record the maximum analysis time and dropped count; host tests cannot prove the hardware timing budget.

Test `music 1 pause`, `music 1 resume`, `music 1 next`, and `music 1 stop`. Bars should clear on pause/stop and follow the next track. Test volume 0 (silence and blank bars), then restore a comfortable volume. Switch LED basic/weather modes and return to music; old bars must not remain.

With the existing local audio command, establish a call and toggle `ptt 1 on` / `ptt 1 off`. Confirm both voice directions still work and music EQ traffic stops during the call. After ending the call, verify the normal music resume behavior and new EQ updates. Keep the confirmed DAC SCK-to-GND wiring.

Analysis uses a 256-point Hann-window FFT at a display analysis rate of 16 kHz and about 3 KB of static state, without heap allocation. The fractional box decimator is intended for a visual display, not a precision spectrum instrument. Stereo channels are averaged. The nominal EQ traffic is 18 bytes × 10/s on the existing 115200-baud UART (about 1.6% with serial framing).
