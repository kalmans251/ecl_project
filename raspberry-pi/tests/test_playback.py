import ctypes as C
import ctypes.util
import math
import unittest
from voice.playback import Codec2Decoder, PlaybackBuffer, upsample


class PlaybackTests(unittest.TestCase):
    def test_prebuffer_underflow_and_resume(self):
        buf = PlaybackBuffer(rate=8000, buffer_ms=160)
        pcm = b'\x01\x00' * 1280
        buf.push(pcm[:320])
        self.assertEqual(buf.read(160), bytes(320))
        buf.push(pcm[320:])
        self.assertEqual(buf.read(1280), pcm)
        self.assertEqual(buf.read(160), bytes(320))
        self.assertEqual(buf.underflows, 1)
        buf.push(pcm)
        self.assertEqual(buf.read(160), pcm[:320])

    def test_latency_is_bounded(self):
        buf = PlaybackBuffer(rate=8000, buffer_ms=160)
        buf.push(bytes(40000))
        self.assertEqual(len(buf.data), 32000)
        self.assertEqual(buf.overflow_samples, 4000)
        buf.clear()
        self.assertFalse(buf.playing)
        self.assertEqual(len(buf.data), 0)

    def test_upsampling(self):
        self.assertEqual(upsample(b'\x01\x00\xfe\xff', 2), b'\x01\x00'*2 + b'\xfe\xff'*2)

    @unittest.skipUnless(ctypes.util.find_library('codec2'), 'requires libcodec2')
    def test_real_codec2_encode_decode(self):
        decoder = Codec2Decoder()
        lib = decoder.lib
        lib.codec2_encode.argtypes = [C.c_void_p, C.POINTER(C.c_ubyte), C.POINTER(C.c_short)]
        lib.codec2_encode.restype = None
        encoder = lib.codec2_create(1)
        self.assertTrue(encoder)
        try:
            encoded = bytearray()
            for frame in range(8):
                pcm = (C.c_short * 160)(*[int(8000 * math.sin(2 * math.pi * 440 * (frame*160+i)/8000)) for i in range(160)])
                bits = (C.c_ubyte * 6)()
                lib.codec2_encode(encoder, bits, pcm)
                encoded.extend(bytes(bits))
            decoded = decoder.decode(bytes(encoded))
            self.assertEqual(len(decoded), 8 * 160 * 2)
            self.assertNotEqual(decoded, bytes(len(decoded)))
            with self.assertRaises(ValueError):
                decoder.decode(b'bad')
        finally:
            lib.codec2_destroy(encoder)
            decoder.close()
            decoder.close()
