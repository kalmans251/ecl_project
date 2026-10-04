import queue
import threading
import time
import unittest

from audio import AudioManager
from plc import PlcBus
from protocol import (AudioDataType, AudioDirection, AudioEvent, CallOrigin,
                      Command, Frame, Node, Service)
from railing import RailingManager
from voice import VoiceRelay


class SerialStub:
    def __init__(self):
        self.rx = queue.Queue()
        self.writes = []
        self.busy = False

    @property
    def in_waiting(self):
        return 1 if self.busy else 0

    def read(self, size):
        try:
            return self.rx.get(timeout=0.01)
        except queue.Empty:
            return b""

    def write(self, raw):
        self.writes.append(Frame.decode(raw))
        return len(raw)

    def flush(self):
        pass

    def close(self):
        pass


def control(rail=1):
    return Frame(rail, Node.PI, Node.P4, Service.AUDIO, Command.SET,
                 bytes([AudioDirection.CONTROL_TX]))


def grant(rail=1, duration=60):
    return Frame(rail, Node.P4, Node.PI, Service.AUDIO, Command.DATA,
                 bytes([AudioDataType.CONTROL_WINDOW]) + duration.to_bytes(2, "big"))


def direction_event(rail, direction):
    return Frame(rail, Node.P4, Node.PI, Service.AUDIO, Command.DATA,
                 bytes([AudioDataType.EVENT, AudioEvent.DIRECTION_CHANGED,
                        CallOrigin.EMERGENCY, direction]))


class ControlWindowTests(unittest.TestCase):
    def setUp(self):
        self.bus = PlcBus()
        self.serial = SerialStub()
        self.bus._serial = self.serial
        self.reader = threading.Thread(target=self.bus._reader_loop)
        self.bus._reader_thread = self.reader
        self.reader.start()

    def tearDown(self):
        self.bus.close()

    def pending_command(self, timeout=0.2):
        results = []
        def send():
            try:
                self.bus.send_control_frame(control(), wait_for_window=True, timeout=timeout)
                results.append("sent")
            except Exception as exc:
                results.append(exc)
        thread = threading.Thread(target=send)
        thread.start()
        deadline = time.monotonic() + 0.1
        while time.monotonic() < deadline:
            with self.bus._pending_lock:
                if self.bus._pending:
                    return thread, results
            time.sleep(0.001)
        self.fail("command did not queue")

    def test_waits_for_matching_grant_and_handles_fragmentation(self):
        thread, results = self.pending_command()
        self.serial.rx.put(grant(rail=2).encode())
        self.serial.rx.put(grant(duration=20).encode())
        raw = grant().encode()
        self.serial.rx.put(raw[:5])
        self.serial.rx.put(raw[5:])
        thread.join(0.5)
        self.assertEqual(results, ["sent"])
        self.assertEqual(self.serial.writes, [control()])

    def test_late_grant_cannot_execute_timed_out_command(self):
        thread, results = self.pending_command(timeout=0.02)
        thread.join(0.2)
        self.assertIsInstance(results[0], TimeoutError)
        self.serial.rx.put(grant().encode())
        self.reader.join(0.03)
        self.assertEqual(self.serial.writes, [])

    def test_grant_followed_by_another_frame_is_not_a_fresh_window(self):
        thread, results = self.pending_command(timeout=0.03)
        later = Frame(1, Node.S3, Node.PI, Service.AUDIO, Command.DATA, b"\x02")
        self.serial.rx.put(grant().encode() + later.encode())
        thread.join(0.2)
        self.assertIsInstance(results[0], TimeoutError)
        self.assertEqual(self.serial.writes, [])

    def test_busy_serial_rejects_grant(self):
        self.serial.busy = True
        thread, results = self.pending_command(timeout=0.03)
        self.serial.rx.put(grant().encode())
        thread.join(0.2)
        self.assertIsInstance(results[0], TimeoutError)
        self.assertEqual(self.serial.writes, [])

    def test_partial_next_frame_also_invalidates_grant(self):
        thread, results = self.pending_command(timeout=0.03)
        self.serial.rx.put(grant().encode() + b"\xa5\x5a\x37")
        thread.join(0.2)
        self.assertIsInstance(results[0], TimeoutError)
        self.assertEqual(self.serial.writes, [])

    def test_grant_dispatch_precedes_slow_frame_callback(self):
        blocker = threading.Event()
        self.bus.set_frame_handler(lambda frame: blocker.wait(0.2))
        thread, results = self.pending_command()
        audio = Frame(1, Node.S3, Node.PI, Service.AUDIO, Command.DATA, b"\x02")
        self.serial.rx.put(audio.encode() + grant().encode())
        thread.join(0.1)
        blocker.set()
        self.assertEqual(results, ["sent"])


class ConfirmedDirectionTests(unittest.TestCase):
    def make_manager(self, direction=AudioDirection.FIELD_TX, attempts=2):
        self.railings = RailingManager()
        self.railings.call_started(1, CallOrigin.EMERGENCY, direction)
        class Bus:
            def __init__(self):
                self.sent = []
                self.callback = lambda frame: None
            def send_control_frame(self, frame, **kwargs):
                self.sent.append((frame, kwargs))
                self.callback(frame)
        self.bus = Bus()
        self.audio = AudioManager(self.bus, self.railings,
                                  ack_timeout=0.01, attempts=attempts)

    def test_lost_first_request_is_retried_and_confirmed(self):
        self.make_manager()
        def acknowledge(frame):
            if len(self.bus.sent) == 2:
                self.audio.handle_frame(direction_event(1, AudioDirection.CONTROL_TX))
        self.bus.callback = acknowledge
        self.audio.set_direction(1, AudioDirection.CONTROL_TX)
        self.assertEqual(len(self.bus.sent), 2)
        self.assertTrue(all(kwargs["wait_for_window"] for _, kwargs in self.bus.sent))

    def test_existing_cached_direction_is_not_confirmation(self):
        self.make_manager(direction=AudioDirection.CONTROL_TX)
        with self.assertRaises(TimeoutError):
            self.audio.set_direction(1, AudioDirection.CONTROL_TX)
        self.assertEqual(len(self.bus.sent), 2)

    def test_other_railing_ack_does_not_confirm(self):
        self.make_manager()
        self.railings.call_started(2, CallOrigin.EMERGENCY, AudioDirection.FIELD_TX)
        self.bus.callback = lambda frame: self.audio.handle_frame(
            direction_event(2, AudioDirection.CONTROL_TX))
        with self.assertRaises(TimeoutError):
            self.audio.set_direction(1, AudioDirection.CONTROL_TX)
        self.assertEqual(self.railings.get_call_direction(1), AudioDirection.FIELD_TX)

    def test_call_end_interrupts_confirmation_wait(self):
        self.make_manager()
        self.bus.callback = lambda frame: self.audio.handle_frame(Frame(
            1, Node.P4, Node.PI, Service.AUDIO, Command.DATA,
            bytes([AudioDataType.EVENT, AudioEvent.CALL_ENDED, CallOrigin.EMERGENCY, 0])))
        with self.assertRaisesRegex(RuntimeError, "Call ended"):
            self.audio.set_direction(1, AudioDirection.CONTROL_TX)

    def test_tcp_queue_keeps_latest_packets_without_sending_in_reader(self):
        self.make_manager()
        relay = VoiceRelay(self.bus, self.railings)
        class Socket:
            def sendall(self, data):
                raise AssertionError("PLC reader attempted TCP write")
        relay._clients.add(Socket())
        relay._broadcast(b"old")
        relay._broadcast(b"middle")
        relay._broadcast(b"latest")
        self.assertEqual(relay.network_dropped_packets, 1)
        self.assertEqual(relay._outbound.get_nowait(), b"middle")
        self.assertEqual(relay._outbound.get_nowait(), b"latest")
