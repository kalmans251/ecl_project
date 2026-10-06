import unittest

from protocol import (
    Command,
    Frame,
    FrameParser,
    Node,
    Service,
    crc16_ccitt_false,
)


class ProtocolTests(unittest.TestCase):
    def test_crc_reference_vector(self) -> None:
        self.assertEqual(
            crc16_ccitt_false(
                b"123456789"
            ),
            0x29B1,
        )

    def test_frame_round_trip(self) -> None:
        frame = Frame(
            railing_id=1,
            src=Node.PI,
            dst=Node.P4,
            service=Service.SYSTEM,
            command=Command.ECHO,
            payload=b"abc",
        )

        encoded = frame.encode()
        decoded = Frame.decode(encoded)

        self.assertEqual(
            decoded,
            frame,
        )

    def test_zero_direction_hangup_event_and_crc_diagnostic(self) -> None:
        raw = bytes.fromhex('a5 5a 04 01 02 01 05 23 01 02 00 00 2d 5b')
        parser = FrameParser()
        self.assertEqual(parser.feed(raw[:10]), [])
        frames = parser.feed(raw[10:])
        self.assertEqual(frames[0].payload, bytes([1, 2, 0, 0]))
        damaged = bytearray(raw)
        damaged[-1] ^= 1
        with self.assertLogs('protocol.parser', level='DEBUG') as output:
            frames = parser.feed(bytes(damaged) + raw)
        self.assertEqual(len(frames), 1)
        self.assertIn('CRC mismatch', output.output[0])

    def test_stream_parser_handles_noise_and_chunks(self) -> None:
        first = Frame(
            railing_id=1,
            src=Node.P4,
            dst=Node.PI,
            service=Service.EMERGENCY,
            command=Command.START,
            payload=b"\x01\x00\x00\x00\x05",
        )

        second = Frame(
            railing_id=2,
            src=Node.P4,
            dst=Node.PI,
            service=Service.SYSTEM,
            command=Command.PONG,
        )

        stream = (
            b"\x00\xFFnoise"
            + first.encode()
            + second.encode()
        )

        parser = FrameParser()

        frames = []

        for index in range(
            0,
            len(stream),
            3,
        ):
            frames.extend(
                parser.feed(
                    stream[
                        index : index + 3
                    ]
                )
            )

        self.assertEqual(
            frames,
            [first, second],
        )


if __name__ == "__main__":
    unittest.main()
