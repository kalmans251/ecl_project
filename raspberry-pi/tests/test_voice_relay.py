import unittest

from protocol import (
    AudioDirection,
    CallOrigin,
    Codec2Mode,
    Command,
    Frame,
    Node,
    Service,
)
from railing import RailingManager
from voice import (
    VoicePacket,
    VoiceRelay,
    VoiceStreamParser,
)


class FakeBus:
    def __init__(self) -> None:
        self.sent = []

    def send_frame(self, frame: Frame) -> None:
        self.sent.append(frame)


class CaptureRelay(VoiceRelay):
    def __init__(
        self,
        bus,
        railings,
    ) -> None:
        super().__init__(
            bus,
            railings,
            host="127.0.0.1",
            port=0,
        )
        self.broadcasts = []

    def _broadcast(
        self,
        data: bytes,
    ) -> None:
        self.broadcasts.append(
            data
        )


def make_packet(
    direction: AudioDirection,
    sequence: int = 7,
) -> VoicePacket:
    return VoicePacket(
        railing_id=1,
        direction=int(direction),
        mode=int(
            Codec2Mode.MODE_2400
        ),
        sequence=sequence,
        frame_count=8,
        bytes_per_frame=6,
        data=bytes(
            range(48)
        ),
    )


class VoicePacketTests(unittest.TestCase):
    def test_network_round_trip(self) -> None:
        packet = make_packet(
            AudioDirection.CONTROL_TX
        )

        decoded = VoicePacket.decode_network(
            packet.encode_network()
        )

        self.assertEqual(
            decoded,
            packet,
        )

    def test_stream_parser_chunks(self) -> None:
        first = make_packet(
            AudioDirection.FIELD_TX,
            10,
        )
        second = make_packet(
            AudioDirection.CONTROL_TX,
            11,
        )

        raw = (
            b"noise"
            + first.encode_network()
            + second.encode_network()
        )

        parser = VoiceStreamParser()
        packets = []

        for index in range(
            0,
            len(raw),
            5,
        ):
            packets.extend(
                parser.feed(
                    raw[
                        index:index + 5
                    ]
                )
            )

        self.assertEqual(
            packets,
            [first, second],
        )

    def test_control_packet_forwards_to_wroom(
        self,
    ) -> None:
        bus = FakeBus()
        railings = RailingManager()

        railings.call_started(
            1,
            int(
                CallOrigin.EMERGENCY
            ),
            int(
                AudioDirection.CONTROL_TX
            ),
        )

        relay = VoiceRelay(
            bus,
            railings,
        )

        packet = make_packet(
            AudioDirection.CONTROL_TX
        )

        self.assertTrue(
            relay.forward_control_packet(
                packet
            )
        )

        self.assertEqual(
            len(bus.sent),
            1,
        )

        frame = bus.sent[0]

        self.assertEqual(
            int(frame.dst),
            int(Node.WROOM),
        )
        self.assertEqual(
            int(frame.service),
            int(Service.AUDIO),
        )
        self.assertEqual(
            int(frame.command),
            int(Command.DATA),
        )
        self.assertEqual(
            frame.payload,
            packet.to_audio_payload(),
        )

    def test_field_packet_broadcasts_to_control(
        self,
    ) -> None:
        bus = FakeBus()
        railings = RailingManager()

        railings.call_started(
            1,
            int(
                CallOrigin.EMERGENCY
            ),
            int(
                AudioDirection.FIELD_TX
            ),
        )

        relay = CaptureRelay(
            bus,
            railings,
        )

        packet = make_packet(
            AudioDirection.FIELD_TX,
            55,
        )

        frame = Frame(
            railing_id=1,
            src=Node.S3,
            dst=Node.PI,
            service=Service.AUDIO,
            command=Command.DATA,
            payload=packet.to_audio_payload(),
        )

        self.assertTrue(
            relay.handle_plc_frame(
                frame
            )
        )

        self.assertEqual(
            len(relay.broadcasts),
            1,
        )

        decoded = VoicePacket.decode_network(
            relay.broadcasts[0]
        )

        self.assertEqual(
            decoded,
            packet,
        )

    def test_wrong_direction_is_dropped(
        self,
    ) -> None:
        bus = FakeBus()
        railings = RailingManager()

        railings.call_started(
            1,
            int(
                CallOrigin.EMERGENCY
            ),
            int(
                AudioDirection.FIELD_TX
            ),
        )

        relay = VoiceRelay(
            bus,
            railings,
        )

        self.assertFalse(
            relay.forward_control_packet(
                make_packet(
                    AudioDirection.CONTROL_TX
                )
            )
        )

        self.assertEqual(
            bus.sent,
            [],
        )


if __name__ == "__main__":
    unittest.main()
