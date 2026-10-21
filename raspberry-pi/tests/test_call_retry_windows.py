"""Exercise actual AudioManager against changing remote direction/grant state."""
import unittest
from audio import AudioManager
from emergency import EmergencyManager
from protocol import AudioDirection, AudioEvent, Command, Service
from railing import RailingManager
from test_call_start import event

class Remote:
    def __init__(self, states, mode='idle', lose_first=False):
        self.states=states;self.mode=mode;self.lose_first=lose_first
        self.preparing=False;self.writes=[];self.attempts=[];self.audio=None
    def send_control_frame(self, frame, **options):
        window=options['wait_for_window'];self.attempts.append(window)
        grants=self.preparing or self.mode=='field'
        if window and not grants:
            raise TimeoutError('No fresh P4 control window')
        if not window and self.mode=='field':
            raise AssertionError('Direct retry collided with FIELD audio')
        self.writes.append(frame)
        if self.lose_first:return
        if len(self.writes)==1:
            self.preparing=True
            return  # endpoint preparation starts; no final result yet
        self.preparing=False
        command=frame.command
        if frame.service==Service.EMERGENCY:command=Command.START
        if command==Command.START:
            self.mode='field';kind=AudioEvent.CALL_STARTED;direction=AudioDirection.FIELD_TX;request=0
        elif command==Command.SET:
            direction=frame.payload[0];self.mode='field' if direction==1 else 'control'
            kind=AudioEvent.DIRECTION_CHANGED;request=int.from_bytes(frame.payload[5:9],'big')
        else:
            self.mode='idle';kind=AudioEvent.CALL_ENDED;direction=0;request=0
        if len(self.writes)==2:return  # applied successfully, but reply lost
        sid=self.states.snapshot(1)['call']['session_id']
        self.audio.handle_frame(event(kind=kind,direction=direction,request=request,session=sid))

class RetryWindowTests(unittest.TestCase):
    def setup_remote(self, mode='idle', lose_first=False):
        self.states=RailingManager();self.remote=Remote(self.states,mode,lose_first)
        self.audio=AudioManager(self.remote,self.states,ack_timeout=.001,attempts=4,recovery_grace_seconds=0)
        self.remote.audio=self.audio
        if mode!='idle':
            self.states.reserve_call(1);sid=self.states.snapshot(1)['call']['session_id']
            self.audio.handle_frame(event(session=sid,direction=1 if mode=='field' else 2))
    def test_start_lost_ready_reply_retries_in_field_grant(self):
        self.setup_remote()
        self.assertTrue(self.audio.start_call(1))
        self.assertEqual(self.remote.attempts,[False,True,True])
        self.assertEqual(len({f.payload for f in self.remote.writes}),1)
    def test_emergency_ack_uses_same_granted_retry_path(self):
        self.setup_remote();self.states.emergency_start(1,1,99)
        manager=EmergencyManager(self.remote,self.states,audio=self.audio)
        self.assertEqual(manager.ack(1),99)
        self.assertEqual(self.remote.attempts,[False,True,True])
    def test_ptt_off_lost_reply_does_not_send_into_field_audio(self):
        self.setup_remote('control')
        self.audio.set_direction(1,AudioDirection.FIELD_TX)
        self.assertEqual(self.remote.attempts,[False,True,True])
        self.assertEqual(self.states.snapshot(1)['call']['phase'],'active')
        self.assertEqual(self.states.get_call_direction(1),AudioDirection.FIELD_TX)
    def test_ptt_on_missing_final_reply_stays_unknown_without_direct_fallback(self):
        self.setup_remote('field')
        with self.assertRaises(TimeoutError):self.audio.set_direction(1,AudioDirection.CONTROL_TX)
        self.assertEqual(len(self.remote.writes),2)
        self.assertTrue(all(self.remote.attempts))
        self.assertEqual(self.states.snapshot(1)['call']['phase'],'unknown')
        with self.assertRaises(RuntimeError):self.states.reserve_call(2)
    def test_lost_first_start_never_blindly_retries_direct(self):
        self.setup_remote(lose_first=True)
        with self.assertRaises(TimeoutError):self.audio.start_call(1)
        self.assertEqual(self.remote.attempts,[False,True,True,True])
        self.assertEqual(len(self.remote.writes),1)
        self.assertTrue(self.states.call_pending(1))
    def test_lost_hangup_reply_uses_existing_idle_recovery(self):
        self.setup_remote('control')
        self.assertTrue(self.audio.end_call(1))
        self.assertEqual(self.remote.attempts,[False,True,True,False])
        self.assertFalse(self.states.call_pending(1))

    def test_late_start_confirmation_wins_over_transport_timeout(self):
        self.setup_remote();self.audio._attempts=2
        original=self.remote.send_control_frame
        def send(frame, **kwargs):
            if self.remote.writes:
                sid=self.states.snapshot(1)['call']['session_id']
                self.audio.handle_frame(event(session=sid))
                raise TimeoutError('write completion raced the confirmation')
            original(frame, **kwargs)
        self.remote.send_control_frame=send
        self.assertTrue(self.audio.start_call(1))
        self.assertEqual(self.states.snapshot(1)['call']['phase'],'active')

    def test_end_after_late_start_is_not_reported_as_success(self):
        self.setup_remote();self.audio._attempts=1
        def send(frame, **kwargs):
            sid=self.states.snapshot(1)['call']['session_id']
            self.audio.handle_frame(event(session=sid))
            self.audio.handle_frame(event(kind=AudioEvent.CALL_ENDED,session=sid,direction=0))
            raise TimeoutError('write completion raced END')
        self.remote.send_control_frame=send
        with self.assertRaisesRegex(RuntimeError,'ended'):
            self.audio.start_call(1)
        self.assertFalse(self.states.call_pending(1))
