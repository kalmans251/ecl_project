import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from railing import RailingManager
from audio import AudioManager
from protocol import AudioDirection, AudioEvent, Command
from test_call_start import Bus, event

class LeaseTests(unittest.TestCase):
    def test_restart_recovers_unknown_without_renewing_or_reactivating(self):
        with tempfile.TemporaryDirectory() as folder:
            path=str(Path(folder)/'calls.json')
            original=RailingManager(path)
            original.reserve_call(1)
            original.call_started(1,0,AudioDirection.FIELD_TX)
            restored=RailingManager(path)
            bus=Bus();audio=AudioManager(bus,restored,ack_timeout=0.002)
            self.assertEqual(restored.snapshot(1)['call']['phase'],'unknown')
            audio.renew_calls();self.assertEqual(bus.sent,[])
            audio.handle_frame(event(session=original.snapshot(1)["call"]["session_id"]))
            self.assertIsNone(restored.get_call_direction(1))
            with self.assertRaises(RuntimeError): restored.reserve_call(2)
            bus.callback=lambda f: audio.handle_frame(event(kind=AudioEvent.CALL_ENDED, session=restored.snapshot(1)["call"]["session_id"]))
            self.assertTrue(audio.end_call(1))
            self.assertFalse(RailingManager(path).call_pending(1))
            restored.reserve_call(2)
            self.assertTrue(RailingManager(path).call_pending(2))

    def test_write_failure_prevents_start_transmission(self):
        with tempfile.TemporaryDirectory() as folder:
            states=RailingManager(str(Path(folder)/'calls.json'))
            bus=Bus();audio=AudioManager(bus,states)
            with patch('railing.manager.os.replace',side_effect=OSError('disk full')):
                with self.assertRaises(OSError): audio.start_call(1)
            self.assertEqual(bus.sent,[])
            self.assertTrue(states.call_pending(1))

    def test_corrupt_journal_is_not_silently_reset(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'calls.json'
            for content in ('{broken', '[]', 'null', '{"version":1,"pending":[0]}'):
                path.write_text(content)
                with self.assertRaises(ValueError): RailingManager(str(path))
                self.assertEqual(path.read_text(),content)

    def test_renewal_uses_window_only_for_field_and_skips_unknown(self):
        states=RailingManager();bus=Bus();audio=AudioManager(bus,states)
        states.reserve_call(1)
        audio.handle_frame(event(session=states.snapshot(1)["call"]["session_id"]));audio.renew_calls()
        self.assertEqual(bus.sent[-1][0].command,Command.CALL_KEEPALIVE)
        self.assertTrue(bus.sent[-1][1]['wait_for_window'])
        states.call_direction_changed(1,AudioDirection.CONTROL_TX);audio.renew_calls()
        self.assertFalse(bus.sent[-1][1]['wait_for_window'])
        before=len(bus.sent)
        audio._control_lock.acquire()
        try: audio.renew_calls()
        finally: audio._control_lock.release()
        self.assertEqual(len(bus.sent),before)
        states.call_end_requested(1);states.call_request_failed(1);audio.renew_calls()
        self.assertEqual(len(bus.sent),before)
