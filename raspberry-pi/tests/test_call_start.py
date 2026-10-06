import io
import sys
import threading
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from audio import AudioManager
from protocol import AudioDataType, AudioDirection, AudioEvent, CallOrigin, Command, Frame, Node, Service
from railing import RailingManager


def event(railing=1, kind=AudioEvent.CALL_STARTED, src=Node.P4, direction=AudioDirection.FIELD_TX):
    return Frame(railing, src, Node.PI, Service.AUDIO, Command.DATA,
                 bytes([AudioDataType.EVENT, kind, CallOrigin.NORMAL, direction]))


class Bus:
    def __init__(self):
        self.sent = []
        self.callback = lambda frame: None
    def send_control_frame(self, frame, **kwargs):
        self.sent.append((frame, kwargs))
        self.callback(frame)


class CallStartTests(unittest.TestCase):
    def setUp(self):
        self.states = RailingManager()
        self.bus = Bus()
        self.audio = AudioManager(self.bus, self.states, ack_timeout=0.02, attempts=2)

    def test_confirmed_start_is_pi_to_p4_and_repeat_is_noop(self):
        self.bus.callback = lambda frame: self.audio.handle_frame(event())
        self.assertTrue(self.audio.start_call(1))
        frame, kwargs = self.bus.sent[0]
        self.assertEqual((frame.src, frame.dst, frame.service, frame.command, frame.payload),
                         (Node.PI, Node.P4, Service.AUDIO, Command.START, b''))
        self.assertTrue(kwargs['wait_for_window'])
        self.assertEqual(self.states.get_call_direction(1), AudioDirection.FIELD_TX)
        self.assertFalse(self.audio.start_call(1))
        self.assertEqual(len(self.bus.sent), 1)

    def test_missing_confirmation_does_not_activate_audio(self):
        with self.assertRaises(TimeoutError):
            self.audio.start_call(1)
        self.assertEqual(len(self.bus.sent), 2)
        self.assertIsNone(self.states.get_call_direction(1))
        with self.assertRaises(RuntimeError):
            self.audio.set_direction(1, AudioDirection.CONTROL_TX)

    def test_lost_request_retries(self):
        def confirm(frame):
            if len(self.bus.sent) == 2:
                self.audio.handle_frame(event())
        self.bus.callback = confirm
        self.assertTrue(self.audio.start_call(1))
        self.assertEqual(len(self.bus.sent), 2)

    def test_other_railing_or_wrong_source_does_not_confirm(self):
        for response in (event(railing=2), event(src=Node.WROOM), event(direction=255)):
            with self.subTest(response=response):
                self.setUp()
                self.bus.callback = lambda frame: self.audio.handle_frame(response)
                with self.assertRaises(TimeoutError):
                    self.audio.start_call(1)
                self.assertIsNone(self.states.get_call_direction(1))

    def test_async_confirmation_wakes_waiter(self):
        delivered = threading.Event()
        def confirm(frame):
            def receive():
                delivered.wait(0.005)
                self.audio.handle_frame(event())
            self.worker = threading.Thread(target=receive)
            self.worker.start()
        self.bus.callback = confirm
        self.assertTrue(self.audio.start_call(1))
        self.worker.join()
        self.assertEqual(len(self.bus.sent), 1)

    def test_grant_timeout_can_retry(self):
        def confirm(frame):
            if len(self.bus.sent) == 1:
                raise TimeoutError('No window')
            self.audio.handle_frame(event())
        self.bus.callback = confirm
        self.assertTrue(self.audio.start_call(1))

    def test_call_ended_during_confirmation_is_not_success(self):
        def confirm(frame):
            self.audio.handle_frame(event())
            self.audio.handle_frame(event(kind=AudioEvent.CALL_ENDED))
        self.bus.callback = confirm
        with self.assertRaisesRegex(RuntimeError, 'ended'):
            self.audio.start_call(1)

    def test_busy_emergency_and_invalid_ids_send_nothing(self):
        self.states.call_started(2, CallOrigin.NORMAL, AudioDirection.FIELD_TX)
        with self.assertRaisesRegex(RuntimeError, 'Another'):
            self.audio.start_call(1)
        self.states.call_ended(2)
        self.states.emergency_start(1, 1, 123)
        with self.assertRaisesRegex(RuntimeError, 'emergency'):
            self.audio.start_call(1)
        for railing in (0, -1, 256):
            with self.assertRaises(ValueError):
                self.audio.start_call(railing)
        self.assertEqual(self.bus.sent, [])

    def test_console_start_ptt_and_hangup(self):
        import main
        class ConsoleBus(Bus):
            def open(self): pass
            def close(self): self.closed = True
            def set_frame_handler(self, handler): self.handler = handler
            def send_control_frame(self, frame, **kwargs):
                self.sent.append((frame, kwargs))
                if frame.command == Command.START:
                    self.handler(event())
                elif frame.command == Command.SET:
                    self.handler(event(kind=AudioEvent.DIRECTION_CHANGED, direction=frame.payload[0]))
                elif frame.command == Command.STOP:
                    self.handler(event(kind=AudioEvent.CALL_ENDED))
        bus = ConsoleBus()
        output = io.StringIO()
        with patch.object(sys, 'argv', ['main.py', '--disable-voice-relay']), \
                patch('main.PlcBus', return_value=bus), \
                patch('builtins.input', side_effect=['call', 'call nonsense', 'call 0', 'call 1',
                    'call 1', 'ptt 1 on', 'ptt 1 off', 'hangup 1', 'quit']), \
                redirect_stdout(output):
            self.assertEqual(main.main(), 0)
        self.assertEqual([frame.command for frame, _ in bus.sent],
                         [Command.START, Command.SET, Command.SET, Command.STOP])
        self.assertIn('CALL confirmed rail=1', output.getvalue())
        self.assertIn('CALL already active rail=1', output.getvalue())
        self.assertTrue(bus.closed)
