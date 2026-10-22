# MP3 header-first timeline

## Why this changed

The previous scanner refilled/moved a 16 KB buffer after each frame and yielded one
10 ms tick every 32 reads (at most 16 KB). Large normal files could exceed the 5 s
startup deadline from these deliberate sleeps alone, leaving duration unknown and
seek disabled despite successful playback.

## New behavior

After existing ID3v2 skipping, read at most 2048 bytes. A valid first-frame
Xing/Info frame count or VBRI v1 frame count supplies duration immediately. Check
MPEG version/layer/rate, frame bounds, count, and optional declared byte count
against actual file size. TLEN and a guessed constant bitrate are not used.
Header layouts follow LAME libmp3lame/VbrTag.c and FFmpeg libavformat/mp3dec.c.

If valid metadata is absent, count frames with a bounded 5 s scan. The scan now
consumes frames via a cursor and compacts/refills only near a block boundary.
SD transfers keep the existing DMA-safe 512-byte scratch buffer. Cooperative
one-tick yields occur after 100 ms elapsed processing, not every 32 read calls.
No new task or permanent audio/MP3 buffer is allocated.

For header-based duration, seek capability is available during playback without
building the entire index at startup. On a seek cache miss, scan frame headers
only through the requested target, using the existing mono-to-stereo output
scratch buffer and a separate temporary header decoder. Restore the original
file cursor afterwards; normal playback decoder/input remain untouched if the
scan is cancelled. Pause the I2S output during this work. Reuse an indexed prefix
for subsequent covered targets. A later target outside that prefix scans from
start again; Xing/VBRI approximate seek tables are not used as exact offsets.
Then decode/discard preceding frames to restore MP3 reservoir/filter state, and
confirm only after the first target PCM write. Existing playback identity and
7 s seek / 8 s Pi confirmation budgets remain. A failed lazy scan does not erase
header duration or permanently disable another explicit seek attempt.

Total duration is encoded-frame timing, not gapless trimming. Xing counts can
exclude the metadata frame that the current PCM decoder processes, so the end
position and metadata duration can differ by about one frame. Playback and
on-demand indexing use the same frame coordinate; seeking is frame-granular.
Malformed metadata can still be inaccurate; duration is not proof of a complete
playable file. If metadata is absent and full fallback scanning cannot finish,
length remains unknown and seek unavailable for that playback. This is logged.

## Device check (WROOM reflash required)

1. Restart the track after flashing. Look for:
   `Timeline source=Info` or `source=Xing` or `source=VBRI`, `index=on demand`,
   `bytes=2048`, and `duration_ms=...`.
2. Pi: `music 1 status` should show length and, while playing, `seekable: true`.
3. `music 1 seek 10`, then a later and earlier target. Confirm actual sound and time.
4. Try a target beyond duration; it must be rejected. Test pause/stop/call during
   scanning; normal controls must still be consumed and stale seek must not succeed.
5. A tagless file should log `source=frame scan`. Failures log reason/bytes/elapsed_ms.

Host tests cover generated CBR/VBR/tagless files, bounded prefix indexing, exact
seek PCM against continuous decoding, malformed and synthetic VBRI/low-rate
headers, and cancellation preserving the playback decoder/buffer/file position.
Hardware SD latency, stack margin, audio resumption and interruption need device tests.
