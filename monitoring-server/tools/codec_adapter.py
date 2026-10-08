"""Loopback-only Codec2 2400 adapter. PCM is 8 kHz mono signed int16 LE.
Install libcodec2-dev (Linux) or set CODEC2_LIBRARY to the Codec2 DLL path.
No browser or device can connect to this service directly.
"""
import ctypes as C
import ctypes.util
import hmac
import os
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Codec:
    def __init__(self):
        self.lib = C.CDLL(os.environ.get("CODEC2_LIBRARY") or ctypes.util.find_library("codec2") or "libcodec2.so")
        self.lib.codec2_create.argtypes = [C.c_int]
        self.lib.codec2_create.restype = C.c_void_p
        self.lib.codec2_destroy.argtypes = [C.c_void_p]
        self.lib.codec2_encode.argtypes = [C.c_void_p, C.POINTER(C.c_ubyte), C.POINTER(C.c_short)]
        self.lib.codec2_decode.argtypes = [C.c_void_p, C.POINTER(C.c_short), C.POINTER(C.c_ubyte)]
        self.lib.codec2_samples_per_frame.argtypes = [C.c_void_p]
        self.lib.codec2_bits_per_frame.argtypes = [C.c_void_p]
        self.states = {}
        self.lock = threading.Lock()

    def convert(self, call, action, data):
        if len(data) != (2560 if action == "encode" else 48):
            raise ValueError("Expected exactly 8 frames")
        with self.lock:
            now = time.monotonic()
            for key, (state, touched) in list(self.states.items()):
                if now - touched > 60:
                    self.lib.codec2_destroy(state)
                    del self.states[key]
            key = (call, action)
            if key not in self.states:
                if len(self.states) >= 128:
                    raise ValueError("Too many active streams")
                state = self.lib.codec2_create(1)  # upstream mode, not wire mode
                if not state:
                    raise ValueError("Codec creation failed")
                if self.lib.codec2_samples_per_frame(state) != 160 or self.lib.codec2_bits_per_frame(state) != 48:
                    self.lib.codec2_destroy(state)
                    raise ValueError("Unexpected Codec2 frame geometry")
                self.states[key] = (state, now)
            state, _ = self.states[key]
            self.states[key] = (state, now)
            result = bytearray()
            for n in range(8):
                if action == "encode":
                    pcm = (C.c_short * 160).from_buffer_copy(data[n * 320:(n + 1) * 320])
                    bits = (C.c_ubyte * 6)()
                    self.lib.codec2_encode(state, bits, pcm)
                    result.extend(bytes(bits))
                else:
                    bits = (C.c_ubyte * 6).from_buffer_copy(data[n * 6:(n + 1) * 6])
                    pcm = (C.c_short * 160)()
                    self.lib.codec2_decode(state, pcm, bits)
                    result.extend(bytes(pcm))
            return bytes(result)


def serve():
    if sys.byteorder != "little":
        raise RuntimeError("Little-endian host required")
    token = os.environ.get("CODEC_TOKEN", "")
    if len(token) < 32:
        raise RuntimeError("Set CODEC_TOKEN of at least 32 characters")
    codec = Codec()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            self.connection.settimeout(2)
            if not hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + token):
                self.send_error(401)
                return
            match = re.fullmatch(r"/(encode|decode)/([0-9a-f-]{36})", self.path)
            try:
                if not match or self.headers.get("Transfer-Encoding") or int(self.headers.get("Content-Length", "0")) not in (48, 2560):
                    raise ValueError()
                data = self.rfile.read(int(self.headers["Content-Length"]))
                result = codec.convert(match[2], match[1], data)
            except (ValueError, TimeoutError):
                self.send_error(400)
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(result)))
            self.end_headers()
            self.wfile.write(result)

    class Server(ThreadingHTTPServer):
        daemon_threads = True
        request_queue_size = 32

    Server(("127.0.0.1", int(os.environ.get("CODEC_PORT", "9200"))), Handler).serve_forever()


if __name__ == "__main__":
    serve()
