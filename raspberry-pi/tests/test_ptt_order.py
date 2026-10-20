import unittest
from audio import AudioManager
from railing import RailingManager
from protocol import AudioEvent,AudioDirection,Command
from test_call_start import Bus,event

class PttOrderTests(unittest.TestCase):
    def setUp(self):
        self.states=RailingManager();self.states.reserve_call(1)
        self.sid=self.states.snapshot(1)['call']['session_id']
        self.bus=Bus();self.audio=AudioManager(self.bus,self.states,ack_timeout=.002,attempts=2)
        self.audio.handle_frame(event(session=self.sid))
    def response(self,f,request=None,direction=None):
        return event(kind=AudioEvent.DIRECTION_CHANGED,session=self.sid,
            direction=f.payload[0] if direction is None else direction,
            request=int.from_bytes(f.payload[5:9],'big') if request is None else request)
    def test_old_same_direction_reply_cannot_confirm_new_on(self):
        observed=[]
        def confirm(f):
            request=int.from_bytes(f.payload[5:9],'big');observed.append(request)
            if request==3:
                self.audio.handle_frame(self.response(f,request=1))
                self.assertEqual(self.states.snapshot(1)['call']['phase'],'switching')
                self.assertNotEqual(self.audio._direction_revision.get(1),3)
            self.audio.handle_frame(self.response(f))
        self.bus.callback=confirm
        for direction in (AudioDirection.CONTROL_TX,AudioDirection.FIELD_TX,AudioDirection.CONTROL_TX):
            self.audio.set_direction(1,direction)
        self.assertEqual(observed,[1,2,3])
        self.audio.handle_frame(event(session=self.sid)) # delayed STARTED cannot undo PTT
        self.assertEqual(self.states.get_call_direction(1),AudioDirection.CONTROL_TX)
    def test_retry_reuses_id_and_wrong_direction_does_not_confirm(self):
        def confirm(f):
            if len(self.bus.sent)==1:
                self.audio.handle_frame(self.response(f,direction=AudioDirection.FIELD_TX))
                return
            self.audio.handle_frame(self.response(f))
        self.bus.callback=confirm
        self.audio.set_direction(1,AudioDirection.CONTROL_TX)
        self.assertEqual(self.bus.sent[0][0].payload,self.bus.sent[1][0].payload)
        self.assertEqual(len(self.bus.sent[0][0].payload),9)
    def test_timeout_keeps_unknown_and_late_reply_cannot_restore_audio(self):
        with self.assertRaises(TimeoutError):self.audio.set_direction(1,AudioDirection.CONTROL_TX)
        self.audio.handle_frame(self.response(self.bus.sent[-1][0]))
        self.assertEqual(self.states.snapshot(1)['call']['phase'],'unknown')
        self.assertIsNone(self.states.get_call_direction(1))
        self.audio.renew_calls();self.assertEqual(len(self.bus.sent),2)
        with self.assertRaises(RuntimeError):self.audio.set_direction(1,AudioDirection.FIELD_TX)
        self.bus.callback=lambda f:self.audio.handle_frame(event(kind=AudioEvent.CALL_ENDED,session=self.sid))
        self.assertTrue(self.audio.end_call(1))
        self.assertTrue(self.bus.sent[-1][1]['wait_for_window'])
    def test_counter_does_not_wrap_and_resets_for_new_session(self):
        self.audio._ptt_serial[1]=(self.sid,0xffffffff)
        with self.assertRaises(RuntimeError):self.audio.set_direction(1,AudioDirection.CONTROL_TX)
        self.assertEqual(self.bus.sent,[])
        self.states.call_ended(1);self.states.reserve_call(1)
        self.sid=self.states.snapshot(1)['call']['session_id']
        self.audio.handle_frame(event(session=self.sid))
        self.bus.callback=lambda f:self.audio.handle_frame(self.response(f))
        self.audio.set_direction(1,AudioDirection.CONTROL_TX)
        self.assertEqual(int.from_bytes(self.bus.sent[-1][0].payload[5:],'big'),1)
    def test_end_after_ptt_reply_is_not_success(self):
        def confirm(f):
            self.audio.handle_frame(self.response(f))
            self.audio.handle_frame(event(kind=AudioEvent.CALL_ENDED,session=self.sid))
        self.bus.callback=confirm
        with self.assertRaisesRegex(RuntimeError,'ended'):
            self.audio.set_direction(1,AudioDirection.CONTROL_TX)
        self.assertFalse(self.states.call_pending(1))

    def test_confirmation_arriving_with_write_timeout_still_succeeds(self):
        self.audio._attempts=1
        def confirm(f):
            self.audio.handle_frame(self.response(f))
            raise TimeoutError('transport completion raced reply')
        self.bus.callback=confirm
        self.audio.set_direction(1,AudioDirection.CONTROL_TX)
        self.assertEqual(self.states.snapshot(1)['call']['phase'],'active')
