import unittest
from audio import AudioManager
from emergency import EmergencyManager
from railing import RailingManager
from protocol import Frame, Node, Service, Command, AudioEvent, AudioDirection, AudioDataType
from test_call_start import Bus, event

class ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.states=RailingManager();self.bus=Bus()
        self.audio=AudioManager(self.bus,self.states,ack_timeout=.002,attempts=3)
    def failure(self, node=Node.WROOM, direction=1, request=0, session=None):
        sid=self.states.snapshot(1)['call']['session_id'] if session is None else session
        return Frame(1,Node.P4,Node.PI,Service.AUDIO,Command.DATA,
            bytes([AudioDataType.EVENT,AudioEvent.PREPARATION_FAILED,0,direction])+
            sid.to_bytes(4,'big')+request.to_bytes(4,'big')+bytes([node,2]))
    def test_start_failure_identifies_endpoint_and_retains_ownership(self):
        self.bus.callback=lambda f:self.audio.handle_frame(self.failure(node=Node.S3))
        with self.assertRaisesRegex(RuntimeError,'S3 microphone'):
            self.audio.start_call(1)
        self.assertTrue(self.states.call_pending(1))
        self.assertIsNone(self.states.get_call_direction(1))
    def test_ptt_failure_is_correlated_and_mutes_call(self):
        self.states.reserve_call(1);sid=self.states.snapshot(1)['call']['session_id']
        self.audio.handle_frame(event(session=sid))
        def callback(f):
            self.audio.handle_frame(self.failure(direction=2,request=99))
            self.assertNotIn(1,self.audio._ready_failures)
            self.audio.handle_frame(self.failure(direction=2,request=1,session=sid^1))
            self.assertNotIn(1,self.audio._ready_failures)
            self.audio.handle_frame(self.failure(direction=2,request=1))
        self.bus.callback=callback
        with self.assertRaisesRegex(RuntimeError,'WROOM output'):
            self.audio.set_direction(1,AudioDirection.CONTROL_TX)
        self.assertEqual(self.states.snapshot(1)['call']['phase'],'unknown')
        self.assertIsNone(self.states.get_call_direction(1))
    def test_stop_failure_does_not_release_shared_bus(self):
        self.states.reserve_call(1);sid=self.states.snapshot(1)['call']['session_id']
        self.audio.handle_frame(event(session=sid))
        self.bus.callback=lambda f:self.audio.handle_frame(self.failure(direction=0))
        with self.assertRaisesRegex(RuntimeError,'WROOM output'):
            self.audio.end_call(1)
        self.assertTrue(self.states.call_pending(1))
        with self.assertRaises(RuntimeError):self.states.reserve_call(2)
    def test_emergency_ack_retries_original_request_until_ready(self):
        self.states.emergency_start(1,1,123)
        emergency=EmergencyManager(self.bus,self.states,audio=self.audio)
        def callback(f):
            self.assertEqual((f.service,f.command),(Service.EMERGENCY,Command.SET))
            if len(self.bus.sent)==2:
                sid=self.states.snapshot(1)['call']['session_id']
                self.audio.handle_frame(event(session=sid))
        self.bus.callback=callback
        self.assertEqual(emergency.ack(1),123)
        self.assertEqual(len(self.bus.sent),2)
        self.assertEqual(self.bus.sent[0][0].payload,self.bus.sent[1][0].payload)
        self.assertEqual(self.states.snapshot(1)['call']['phase'],'active')
