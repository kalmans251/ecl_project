# Resume a paused track after sleep and LED mode change

Flash P4 after this change. Pi, WROOM and S3 need no changes for this fix.

Reproduction on the existing Pi console:

```text
projector 1 on
sleep 1 on
led 1 music
music 1 start
```

Keep the radar clear until the idle timeout passes (currently 10 seconds), while the track is still playing. P4 waits for track completion in SLEEP_PENDING. Before the track finishes, run `led 1 basic`: music pauses and LED/projector sleep immediately. Run `led 1 music` while still asleep. Outputs should remain asleep. Trigger a new radar detection. LED/projector should restore and the same paused track should resume, rather than remain paused or advance to a new track.

Expected P4 logs include `RADAR wake`, `OUTPUT RESTORE`, and `WAKE -> RESUME existing track`. WROOM should log `RESUME`; P4 should receive `MUSIC RESUMED`. Repeat this cycle and check sound resumes each time.

Also verify normal sleep after a track finishes: wake must still start NEXT. A music session armed while asleep with no current track must still START. Explicit `music 1 stop` must stay stopped after wake. User pause, call and emergency pause reasons must prevent this wake RESUME until their normal release. With LED BASIC/WEATHER selected, wake must not resume music.

Host test command: `python -m unittest discover -s hello-p4/tests -v`. The regression test uses actual sleep manager, music manager, pause policy and system state with substituted RTOS queues/timing/projector output. It tests the original failing sequence, delayed PAUSED acknowledgement, blocking reasons, stopped sessions and existing NEXT/START paths. Physical UART delivery, radar and projector require board verification.
