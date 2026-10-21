import unittest
from unittest.mock import patch
from protocol import Frame, FrameParser


class ParserIdleTests(unittest.TestCase):
    def feed(self, parser, data, now):
        with patch("protocol.parser.time.monotonic", return_value=now):
            return parser.feed(data)

    def test_observed_short_reply_expires_before_next_response(self):
        parser = FrameParser()
        short = bytes.fromhex("a5 5a 0e 01 02 01 00 2c ac f5 cf a6 00 00 00 51 fe")
        self.assertEqual(self.feed(parser, short, 1), [])
        reply = Frame(1, 2, 1, 0, 0x2c, bytes.fromhex("acf5cfa7") + bytes(10))
        with self.assertLogs("protocol.parser", level="DEBUG") as logs:
            self.assertEqual(self.feed(parser, reply.encode(), 2), [reply])
        self.assertIn("received=17 expected=24", logs.output[0])
        self.assertFalse(any("CRC mismatch" in line for line in logs.output))

    def test_empty_read_expires_and_does_not_repeat_log(self):
        parser = FrameParser()
        self.feed(parser, b"\xa5\x5a\x0e", 1)
        self.assertFalse(parser.expire(1.1))
        with self.assertLogs("protocol.parser", level="DEBUG"):
            self.assertTrue(parser.expire(1.3))
        self.assertEqual(parser.pending_bytes, 0)
        self.assertFalse(parser.expire(2))

    def test_slow_fragmented_frame_with_embedded_header_is_preserved(self):
        parser = FrameParser()
        frame = Frame(1, 2, 1, 5, 0x23, b"\x00\xa5\x5a" * 20)
        output = []
        for i, byte in enumerate(frame.encode()):
            output += self.feed(parser, bytes([byte]), i * 0.05)
        self.assertEqual(output, [frame])  # total duration exceeds timeout

    def test_corrupt_frame_rejected_and_following_valid_frame_recovers(self):
        parser = FrameParser()
        frame = Frame(1, 2, 1, 0, 2, b"\x01")
        corrupt = bytearray(frame.encode()); corrupt[-1] ^= 1
        with self.assertLogs("protocol.parser", level="DEBUG") as logs:
            self.assertEqual(self.feed(parser, bytes(corrupt) + frame.encode(), 1), [frame])
        self.assertTrue(any("CRC mismatch" in line for line in logs.output))

    def test_reset_clears_timestamp_and_partial_header_expires(self):
        parser = FrameParser()
        self.feed(parser, b"\xa5", 1)
        self.assertTrue(parser.expire(1.3))
        self.feed(parser, b"\xa5", 2)
        parser.reset()
        self.assertFalse(parser.expire(4))
