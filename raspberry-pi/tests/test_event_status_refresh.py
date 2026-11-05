"""Output change hints schedule a correlated status query, never synthesize telemetry."""
import threading
import unittest
from types import SimpleNamespace
from plc.events import EventPoller
from protocol import Frame, FrameParser, Node, Service, Command


class OutputRefreshTests(unittest.TestCase):
    def setUp(self):
        self.refreshes = []
        self.dispatched = []
        self.poller = EventPoller(None, None, None, [1, 2], self.dispatched.append,
                                  status_refresh=self.refreshes.append)
        self.token = b'abcd'

    def deliver(self, rail=1, outputs=b'\x00\x01', token=None, corrupt=False, event=False):
        self.poller.pending = (rail, self.token)
        self.poller.received = False
        payload = (self.token if token is None else token)
        payload += (9 if event else 0).to_bytes(4, 'big') + bytes(4)
        payload += (bytes([Service.EMERGENCY, Command.START, 1, 0, 0, 0, 7])
                    if event else bytes(2) + outputs)
        raw = bytearray(Frame(rail, Node.P4, Node.PI, Service.SYSTEM,
                              Command.EVENT_REPLY, payload).encode())
        if corrupt:
            raw[-1] ^= 1
        parser = FrameParser()
        for byte in raw:
            for frame in parser.feed(bytes([byte])):
                self.poller.handle_frame(frame)

    def test_first_observation_and_both_sleep_edges_refresh_once(self):
        self.deliver()
        self.deliver()
        self.assertEqual([1], self.refreshes)
        self.deliver(outputs=b'\x01\x00')
        self.deliver(outputs=b'\x00\x01')
        self.assertEqual([1, 1, 1], self.refreshes)
        self.assertEqual([], self.dispatched)

    def test_rails_are_independent_and_projector_only_change_is_detected(self):
        self.deliver(rail=1)
        self.deliver(rail=2)
        self.deliver(rail=2, outputs=b'\x00\x00')
        self.deliver(rail=1)
        self.assertEqual([1, 2, 2], self.refreshes)

    def test_invalid_crc_token_or_boolean_never_refreshes(self):
        self.deliver(corrupt=True)
        self.deliver(token=b'xxxx')
        self.deliver(outputs=b'\x02\x00')
        self.assertEqual([], self.refreshes)
        self.assertFalse(self.poller.received)
        self.assertEqual({}, self.poller.output_states)

    def test_legacy_empty_reply_and_emergency_keep_working(self):
        self.deliver(outputs=b'')
        self.assertTrue(self.poller.received)
        self.deliver(event=True)
        self.assertEqual(1, len(self.dispatched))
        self.assertEqual(9, self.poller.ack[1])
        self.assertEqual([], self.refreshes)

    def test_callback_only_queues_and_failure_can_retry(self):
        def fail(rail):
            raise RuntimeError('enqueue failed')
        self.poller.status_refresh = fail
        with self.assertRaises(RuntimeError):
            self.deliver()
        self.assertNotIn(1, self.poller.output_states)
        self.poller.status_refresh = self.refreshes.append
        self.deliver()
        self.assertEqual([1], self.refreshes)


if __name__ == '__main__':
    unittest.main()
