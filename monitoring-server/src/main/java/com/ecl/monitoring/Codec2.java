package com.ecl.monitoring;

import com.sun.jna.Library;
import com.sun.jna.Native;
import com.sun.jna.Pointer;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.util.HashMap;
import java.util.Map;
import java.util.UUID;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

/** In-process Codec2 2400. Native pointers never leave this synchronized owner. */
@Component
public final class Codec2 implements AutoCloseable {
    interface Api extends Library {
        Pointer codec2_create(int mode);
        void codec2_destroy(Pointer state);
        void codec2_encode(Pointer state, byte[] bits, short[] speech);
        void codec2_decode(Pointer state, short[] speech, byte[] bits);
        int codec2_samples_per_frame(Pointer state);
        int codec2_bits_per_frame(Pointer state);
    }
    private record Key(String call, String epoch, boolean encode) {}
    private static final class State {
        final Pointer pointer;
        long touched = System.nanoTime();
        State(Pointer pointer) { this.pointer = pointer; }
    }
    private static final Logger LOG = LoggerFactory.getLogger(Codec2.class);
    private static final long IDLE_NANOS = 60_000_000_000L;
    private final Map<Key, State> states = new HashMap<>();
    private Api api;
    private String unavailable;
    private boolean closed;

    public Codec2(PortalSettings settings) {
        try {
            String library = settings.codecLibrary();
            api = Native.load(library == null || library.isBlank() ? "codec2" : library, Api.class);
            Pointer probe = create();
            api.codec2_destroy(probe);
            LOG.info("Codec2 2400 ready in Spring Boot (8000 Hz, 160 samples / 6 bytes)");
        } catch (LinkageError | RuntimeException e) {
            api = null;
            unavailable = e.toString();
            LOG.warn("Web voice unavailable: Codec2 native library could not load. Use the bundled native JAR or set CODEC2_LIBRARY. {}", unavailable);
        }
    }
    public synchronized boolean available() { return api != null && !closed; }
    public synchronized String unavailableReason() { return unavailable; }
    private Pointer create() {
        Pointer pointer = api.codec2_create(1); // Codec2 API mode 2400, not the PLC wire mode
        if (pointer == null) throw new IllegalStateException("Codec2 allocation failed");
        if (api.codec2_samples_per_frame(pointer) != 160 || api.codec2_bits_per_frame(pointer) != 48) {
            api.codec2_destroy(pointer);
            throw new IllegalStateException("Unsupported Codec2 2400 geometry");
        }
        return pointer;
    }
    public synchronized byte[] convert(String call, String epoch, boolean encode, byte[] input) {
        if (!available()) throw new IllegalStateException("Codec2 unavailable: " + unavailable);
        UUID.fromString(call); UUID.fromString(epoch);
        if (input == null || input.length != (encode ? 2560 : 48))
            throw new IllegalArgumentException("Expected exactly eight Codec2 frames");
        clean();
        // A confirmed PTT epoch starts a fresh vocoder state; no old speech tail.
        states.entrySet().removeIf(e -> {
            if (e.getKey().call().equals(call) && !e.getKey().epoch().equals(epoch)) {
                api.codec2_destroy(e.getValue().pointer); return true;
            }
            return false;
        });
        Key key = new Key(call, epoch, encode);
        State state = states.get(key);
        if (state == null) {
            if (states.size() >= 128) throw new IllegalStateException("Too many Codec2 streams");
            state = new State(create()); states.put(key, state);
        }
        state.touched = System.nanoTime();
        ByteBuffer pcm = ByteBuffer.wrap(encode ? input : new byte[2560]).order(ByteOrder.LITTLE_ENDIAN);
        byte[] output = encode ? new byte[48] : pcm.array();
        short[] speech = new short[160]; byte[] bits = new byte[6];
        for (int frame = 0; frame < 8; frame++) {
            if (encode) {
                for (int i = 0; i < 160; i++) speech[i] = pcm.getShort();
                api.codec2_encode(state.pointer, bits, speech);
                System.arraycopy(bits, 0, output, frame * 6, 6);
            } else {
                System.arraycopy(input, frame * 6, bits, 0, 6);
                api.codec2_decode(state.pointer, speech, bits);
                for (short sample : speech) pcm.putShort(sample);
            }
        }
        return output;
    }
    public synchronized void release(String call) {
        states.entrySet().removeIf(e -> {
            if (e.getKey().call().equals(call)) { api.codec2_destroy(e.getValue().pointer); return true; }
            return false;
        });
    }
    @org.springframework.scheduling.annotation.Scheduled(fixedDelay=10000)
    public synchronized void clean() {
        long now = System.nanoTime();
        states.entrySet().removeIf(e -> {
            if (now - e.getValue().touched > IDLE_NANOS) { api.codec2_destroy(e.getValue().pointer); return true; }
            return false;
        });
    }
    synchronized int streamCount() { return states.size(); }
    @jakarta.annotation.PreDestroy
    @Override public synchronized void close() {
        if (closed) return;
        states.values().forEach(s -> api.codec2_destroy(s.pointer));
        states.clear(); closed = true;
    }
}
