"""Optional local Codec2 playback; never runs in the PLC reader thread."""
from __future__ import annotations

from array import array
import ctypes as C
import ctypes.util
import threading


class Codec2Decoder:
    def __init__(self):
        name = ctypes.util.find_library('codec2')
        if not name:
            raise RuntimeError('libcodec2 not found: sudo apt install libcodec2-dev')
        self.lib = C.CDLL(name)
        self.lib.codec2_create.argtypes = [C.c_int]
        self.lib.codec2_create.restype = C.c_void_p
        self.lib.codec2_destroy.argtypes = [C.c_void_p]
        self.lib.codec2_destroy.restype = None
        self.lib.codec2_samples_per_frame.argtypes = [C.c_void_p]
        self.lib.codec2_samples_per_frame.restype = C.c_int
        self.lib.codec2_bits_per_frame.argtypes = [C.c_void_p]
        self.lib.codec2_bits_per_frame.restype = C.c_int
        self.lib.codec2_decode.argtypes = [C.c_void_p, C.POINTER(C.c_short), C.POINTER(C.c_ubyte)]
        self.lib.codec2_decode.restype = None
        self.state = self.lib.codec2_create(1)  # upstream CODEC2_MODE_2400, not wire enum
        if not self.state:
            raise RuntimeError('Codec2 2400 decoder creation failed')
        if (self.lib.codec2_samples_per_frame(self.state) != 160
                or self.lib.codec2_bits_per_frame(self.state) != 48):
            self.close()
            raise RuntimeError('Unexpected Codec2 2400 frame geometry')

    def decode(self, data: bytes) -> bytes:
        if not data or len(data) % 6:
            raise ValueError('Codec2 2400 data must contain complete 6-byte frames')
        if not self.state:
            raise RuntimeError('Decoder is closed')
        result = bytearray()
        for offset in range(0, len(data), 6):
            bits = (C.c_ubyte * 6).from_buffer_copy(data[offset:offset + 6])
            pcm = (C.c_short * 160)()
            self.lib.codec2_decode(self.state, pcm, bits)
            result.extend(bytes(pcm))
        return bytes(result)

    def close(self):
        if self.state:
            self.lib.codec2_destroy(self.state)
            self.state = None


def upsample(pcm: bytes, factor: int) -> bytes:
    """Sample repetition for diagnostic playback at a device-supported rate."""
    if factor == 1:
        return pcm
    samples = array('h')
    samples.frombytes(pcm)
    return array('h', (sample for sample in samples for _ in range(factor))).tobytes()


class PlaybackBuffer:
    def __init__(self, rate=48000, buffer_ms=600, max_ms=2000):
        if not 160 <= buffer_ms < max_ms:
            raise ValueError('buffer_ms must be 160..1999')
        self.rate = rate
        self.target = rate * buffer_ms // 1000 * 2
        self.limit = rate * max_ms // 1000 * 2
        self.lock = threading.Lock()
        self.data = bytearray()
        self.playing = False
        self.underflows = 0
        self.portaudio_underflows = 0
        self.overflow_samples = 0

    def push(self, pcm):
        with self.lock:
            self.data.extend(pcm)
            excess = max(0, len(self.data) - self.limit)
            if excess:
                del self.data[:excess]
                self.overflow_samples += excess // 2

    def clear(self):
        with self.lock:
            self.data.clear()
            self.playing = False

    def read(self, frames):
        count = frames * 2
        with self.lock:
            if not self.playing and len(self.data) >= self.target:
                self.playing = True
            if not self.playing:
                return bytes(count)
            take = min(count, len(self.data))
            result = bytes(self.data[:take])
            del self.data[:take]
            if take < count:
                self.underflows += 1
                self.playing = False
            return result + bytes(count - take)

    def callback(self, outdata, frames, time_info, status):
        if status.output_underflow:
            self.portaudio_underflows += 1
        outdata[:] = self.read(frames)

    def status(self):
        with self.lock:
            return dict(buffer_ms=round(len(self.data) * 1000 / (self.rate * 2)),
                        playing=self.playing, buffer_underflows=self.underflows,
                        device_underflows=self.portaudio_underflows,
                        overflow_samples=self.overflow_samples)
