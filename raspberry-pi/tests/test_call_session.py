import json
import tempfile
import unittest
from pathlib import Path
from audio import AudioManager
from emergency import EmergencyManager
from railing import RailingManager
from protocol import AudioEvent, AudioDirection, Command
from test_call_start import Bus, event

class SessionTests(unittest.TestCase):
    def setUp(self):
        self.states=RailingManager()
        self.bus=Bus()
        self.audio=AudioManager(self.bus,self.states,ack_timeout=.002,attempts=2)

    def test_retries_reuse_id_and_next_call_changes_id(self):
        def reply(f):
            if f.command==Command.START and len(self.bus.sent)==1:return
            kind=AudioEvent.CALL_STARTED if f.command==Command.START else AudioEvent.CALL_ENDED
            self.audio.handle_frame(event(kind=kind,session=int.from_bytes(f.payload[-4:],'big')))
        self.bus.callback=reply
        self.audio.start_call(1)
        first=self.bus.sent[0][0].payload
        self.assertEqual(first,self.bus.sent[1][0].payload)
        self.assertNotEqual(first,bytes(4))
        self.audio.end_call(1)
        self.audio.start_call(1)
        self.assertNotEqual(first,self.bus.sent[-1][0].payload)

    def test_old_or_legacy_events_do_not_mutate_new_call(self):
        self.states.reserve_call(1)
        sid=self.states.snapshot(1)['call']['session_id']
        self.audio.handle_frame(event(session=sid))
        for kind in (AudioEvent.CALL_STARTED,AudioEvent.DIRECTION_CHANGED,AudioEvent.CALL_ENDED):
            self.audio.handle_frame(event(kind=kind,session=sid^1,direction=AudioDirection.CONTROL_TX))
            old=event(kind=kind)
            from dataclasses import replace
            self.audio.handle_frame(replace(old,payload=old.payload[:4]))
            self.assertEqual(self.states.get_call_direction(1),AudioDirection.FIELD_TX)
        self.states.call_end_requested(1)
        self.audio.handle_frame(event(session=sid))
        self.assertEqual(self.states.snapshot(1)['call']['phase'],'ending')
        self.audio.handle_frame(event(kind=AudioEvent.CALL_ENDED,session=sid))
        self.audio.handle_frame(event(session=sid))
        self.assertFalse(self.states.call_pending(1))

    def test_session_survives_restart_and_legacy_journal_migrates(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'state.json'
            states=RailingManager(str(path));states.reserve_call(1)
            sid=states.snapshot(1)['call']['session_id']
            restored=RailingManager(str(path))
            self.assertEqual(restored.snapshot(1)['call']['session_id'],sid)
            self.assertTrue(restored.snapshot(1)['call']['recovered'])
            path.write_text(json.dumps({'version':1,'pending':[2]}))
            migrated=RailingManager(str(path))
            self.assertTrue(migrated.call_pending(2))
            self.assertEqual(migrated.snapshot(2)['call']['session_id'],0)
            self.assertEqual(json.loads(path.read_text())['version'],2)

    def test_emergency_ack_carries_reserved_session(self):
        self.states.emergency_start(1,1,123)
        self.bus.send_frame=lambda f:self.bus.sent.append((f,{}))
        EmergencyManager(self.bus,self.states).ack(1)
        self.assertEqual(len(self.bus.sent[0][0].payload),9)
        self.assertEqual(self.bus.sent[0][0].payload[5:],self.audio.session_bytes(1))

    def test_atomic_state_update_checks_session_again(self):
        self.states.reserve_call(1)
        sid=self.states.snapshot(1)['call']['session_id']
        self.assertFalse(self.states.call_started(1,0,1,session_id=sid^1))
        self.assertFalse(self.states.call_ended(1,session_id=sid^1))
        self.assertTrue(self.states.call_pending(1))
