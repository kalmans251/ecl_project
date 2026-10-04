import unittest

from audio import AudioManager
from emergency import EmergencyManager
from protocol import (
    AudioDataType,
    AudioDirection,
    AudioEvent,
    CallOrigin,
    Command,
    EmergencyEvent,
    EmergencySource,
    Frame,
    Node,
    Service,
)
from railing import RailingManager


class FakeBus:
    def __init__(self) -> None:
        self.sent = []
        self.on_control = None

    def send_frame(self, frame: Frame) -> None:
        self.sent.append(frame)

    def send_control_frame(self, frame, **kwargs):
        self.sent.append(frame)
        if self.on_control:
            self.on_control(frame)


class StateSyncTests(unittest.TestCase):
    def test_emergency_ack_confirmation_clears_emergency(
        self,
    ) -> None:
        railings = RailingManager()
        bus = FakeBus()

        emergency = EmergencyManager(
            bus,
            railings,
        )

        railings.emergency_start(
            1,
            int(EmergencySource.BUTTON),
            1234,
        )

        railings.mark_emergency_ack_sent(
            1,
            1234,
        )

        handled = emergency.handle_frame(
            Frame(
                railing_id=1,
                src=Node.P4,
                dst=Node.PI,
                service=Service.EMERGENCY,
                command=Command.DATA,
                payload=(
                    bytes(
                        [
                            int(
                                EmergencyEvent.ACKED
                            )
                        ]
                    )
                    + (1234).to_bytes(
                        4,
                        "big",
                    )
                ),
            )
        )

        self.assertTrue(handled)

        state = railings.snapshot(1)

        self.assertFalse(
            state["emergency"]["active"]
        )
        self.assertIsNone(
            state["emergency"]["seq"]
        )

    def test_call_state_lifecycle(
        self,
    ) -> None:
        railings = RailingManager()
        bus = FakeBus()

        audio = AudioManager(
            bus,
            railings,
        )

        started = Frame(
            railing_id=1,
            src=Node.P4,
            dst=Node.PI,
            service=Service.AUDIO,
            command=Command.DATA,
            payload=bytes(
                [
                    int(AudioDataType.EVENT),
                    int(
                        AudioEvent.CALL_STARTED
                    ),
                    int(
                        CallOrigin.EMERGENCY
                    ),
                    int(
                        AudioDirection.FIELD_TX
                    ),
                ]
            ),
        )

        self.assertTrue(
            audio.handle_frame(started)
        )

        state = railings.snapshot(1)

        self.assertTrue(
            state["call"]["active"]
        )
        self.assertEqual(
            state["call"]["origin"],
            int(CallOrigin.EMERGENCY),
        )
        self.assertEqual(
            state["call"]["direction"],
            int(
                AudioDirection.FIELD_TX
            ),
        )

        direction = Frame(
            railing_id=1,
            src=Node.P4,
            dst=Node.PI,
            service=Service.AUDIO,
            command=Command.DATA,
            payload=bytes(
                [
                    int(AudioDataType.EVENT),
                    int(
                        AudioEvent.DIRECTION_CHANGED
                    ),
                    int(
                        CallOrigin.EMERGENCY
                    ),
                    int(
                        AudioDirection.CONTROL_TX
                    ),
                ]
            ),
        )

        self.assertTrue(
            audio.handle_frame(direction)
        )

        state = railings.snapshot(1)

        self.assertEqual(
            state["call"]["direction"],
            int(
                AudioDirection.CONTROL_TX
            ),
        )

        ended = Frame(
            railing_id=1,
            src=Node.P4,
            dst=Node.PI,
            service=Service.AUDIO,
            command=Command.DATA,
            payload=bytes(
                [
                    int(AudioDataType.EVENT),
                    int(
                        AudioEvent.CALL_ENDED
                    ),
                    int(
                        CallOrigin.EMERGENCY
                    ),
                    0,
                ]
            ),
        )

        self.assertTrue(
            audio.handle_frame(ended)
        )

        state = railings.snapshot(1)

        self.assertFalse(
            state["call"]["active"]
        )
        self.assertIsNone(
            state["call"]["direction"]
        )

    def test_ptt_and_hangup_commands(
        self,
    ) -> None:
        railings = RailingManager()
        bus = FakeBus()

        audio = AudioManager(
            bus,
            railings,
        )
        railings.call_started(1, CallOrigin.EMERGENCY, AudioDirection.FIELD_TX)
        def acknowledge(frame):
            if frame.command == Command.SET:
                audio.handle_frame(Frame(1, Node.P4, Node.PI, Service.AUDIO,
                    Command.DATA, bytes([AudioDataType.EVENT,
                    AudioEvent.DIRECTION_CHANGED, CallOrigin.EMERGENCY,
                    frame.payload[0]])))
        bus.on_control = acknowledge

        audio.set_direction(
            1,
            AudioDirection.CONTROL_TX,
        )

        self.assertEqual(
            len(bus.sent),
            1,
        )
        self.assertEqual(
            int(bus.sent[0].service),
            int(Service.AUDIO),
        )
        self.assertEqual(
            int(bus.sent[0].command),
            int(Command.SET),
        )
        self.assertEqual(
            bus.sent[0].payload,
            bytes(
                [
                    int(
                        AudioDirection.CONTROL_TX
                    )
                ]
            ),
        )

        audio.end_call(1)

        self.assertEqual(
            len(bus.sent),
            2,
        )
        self.assertEqual(
            int(bus.sent[1].command),
            int(Command.STOP),
        )


if __name__ == "__main__":
    unittest.main()
