package com.ecl.monitoring;

/** Bounded jitter allowance, without buffering audio or closing the call. */
final class VoiceRateLimit {
    static final long PACKET_NANOS = 160_000_000L;
    static final long CAPACITY = 3 * PACKET_NANOS;
    private long credit = CAPACITY;
    private long last;
    private boolean started;

    synchronized boolean allow(long now) {
        if (started) {
            long elapsed = now - last;
            if (elapsed > 0) credit += Math.min(elapsed, CAPACITY - credit);
        }
        last = now;
        started = true;
        if (credit < PACKET_NANOS) return false;
        credit -= PACKET_NANOS;
        return true;
    }
}
