"""Native Codec2 geometry and stream-boundary checks; no audio device required."""
import math
import struct
import unittest
from codec_adapter import Codec


class CodecAdapterTest(unittest.TestCase):
    def test_round_trip_and_frame_geometry(self):
        codec = Codec()
        pcm = struct.pack('<1280h', *[int(5000 * math.sin(i * 2 * math.pi * 440 / 8000)) for i in range(1280)])
        bits = codec.convert('call-a', 'encode', pcm)
        self.assertEqual(48, len(bits))
        output = codec.convert('call-a', 'decode', bits)
        self.assertEqual(2560, len(output))
        self.assertGreater(max(abs(x) for x in struct.unpack('<1280h', output)), 0)

    def test_invalid_geometry_is_rejected(self):
        codec = Codec()
        for action, data in [('encode', b'\0' * 2558), ('decode', b'\0' * 47)]:
            with self.assertRaises(ValueError):
                codec.convert('call-a', action, data)

    def test_calls_and_directions_have_separate_state(self):
        codec = Codec()
        codec.convert('call-a', 'encode', b'\0' * 2560)
        codec.convert('call-b', 'encode', b'\0' * 2560)
        codec.convert('call-a', 'decode', b'\0' * 48)
        self.assertEqual(3, len({state for state, touched in codec.states.values()}))


if __name__ == '__main__':
    unittest.main()
