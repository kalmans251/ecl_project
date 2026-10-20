import threading
import unittest
from audio import AudioManager
from emergency import EmergencyManager
from railing import RailingManager
from protocol import AudioEvent, Command, AudioDirection
from test_call_start import Bus, event

class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.states = RailingManager()
        self.bus = Bus()
        self.bus.send_frame = lambda frame: self.bus.send_control_frame(frame)
        self.audio = AudioManager(self.bus, self.states, ack_timeout=0.002, attempts=2)
        self.emergency = EmergencyManager(self.bus, self.states)

    def lose_start(self):
        with self.assertRaises(TimeoutError):
            self.audio.start_call(1)
        self.assertEqual(self.states.snapshot(1)['call']['phase'], 'unknown')
        self.assertIsNone(self.states.get_call_direction(1))

    def test_lost_start_reply_hangup_reaches_p4_and_releases_bus(self):
        self.lose_start()
        with self.assertRaises(RuntimeError): self.audio.start_call(2)
        self.bus.callback = lambda f: self.audio.handle_frame(event(kind=AudioEvent.CALL_ENDED))
        self.assertTrue(self.audio.end_call(1))
        self.assertEqual(self.bus.sent[-1][0].command, Command.STOP)
        self.assertTrue(self.bus.sent[-1][1]['wait_for_window'])
        self.assertEqual(self.states.snapshot(1)['call']['phase'], 'ended')
        self.bus.callback = lambda f: self.audio.handle_frame(event(railing=2))
        self.assertTrue(self.audio.start_call(2))

    def test_lost_start_request_idle_p4_without_grant(self):
        self.lose_start()
        def idle(f):
            if self.bus.sent[-1][1]['wait_for_window']:
                raise TimeoutError('idle: no grant')
            self.audio.handle_frame(event(kind=AudioEvent.CALL_ENDED))
        self.bus.callback = idle
        self.assertTrue(self.audio.end_call(1))
        self.assertEqual([o['wait_for_window'] for _,o in self.bus.sent[-2:]], [True,False])

    def test_lost_end_retains_reservation_and_blocks_ptt(self):
        self.audio.handle_frame(event())
        with self.assertRaises(TimeoutError): self.audio.end_call(1)
        self.assertEqual(self.states.snapshot(1)['call']['phase'], 'unknown')
        with self.assertRaises(RuntimeError): self.audio.start_call(2)
        with self.assertRaises(RuntimeError): self.audio.set_direction(1, AudioDirection.CONTROL_TX)
        self.bus.callback = lambda f: self.audio.handle_frame(event(kind=AudioEvent.CALL_ENDED))
        self.assertTrue(self.audio.end_call(1))

    def test_other_railing_end_cannot_release_pending_call(self):
        self.lose_start()
        self.audio.handle_frame(event(railing=2, kind=AudioEvent.CALL_ENDED))
        self.assertTrue(self.states.call_pending(1))
        self.audio.handle_frame(event())
        self.assertEqual(self.states.snapshot(1)['call']['phase'], 'active')

    def test_emergency_kept_pending_while_other_call_unknown(self):
        self.lose_start()
        self.states.emergency_start(2,1,123)
        before = len(self.bus.sent)
        with self.assertRaises(RuntimeError): self.emergency.ack(2)
        self.assertEqual(len(self.bus.sent),before)
        self.assertTrue(self.states.snapshot(2)['emergency']['active'])
        self.states.call_ended(1)
        self.emergency.ack(2)
        self.assertEqual(self.states.snapshot(2)['call']['phase'],'unknown')
        with self.assertRaises(RuntimeError): self.audio.start_call(3)

    def test_concurrent_reservations_have_single_winner(self):
        barrier=threading.Barrier(2)
        winners=[]
        def reserve(rail):
            barrier.wait()
            try:
                self.states.reserve_call(rail, emergency=True)
                winners.append(rail)
            except RuntimeError: pass
        threads=[threading.Thread(target=reserve,args=(r,)) for r in (1,2)]
        for t in threads:t.start()
        for t in threads:t.join()
        self.assertEqual(len(winners),1)

    def test_idle_hangup_is_explicit_noop(self):
        self.assertFalse(self.audio.end_call(1))
        self.assertEqual(self.bus.sent,[])

    def test_unknown_call_blocks_general_controls_and_voice(self):
        from device_control import DeviceControls
        from voice import VoiceRelay
        relay=VoiceRelay(self.bus,self.states)
        self.audio.handle_frame(event(direction=AudioDirection.CONTROL_TX))
        self.assertIsNotNone(relay.audio_token(1,AudioDirection.CONTROL_TX))
        self.states.call_end_requested(1)
        self.states.call_request_failed(1)
        self.assertIsNone(relay.audio_token(1,AudioDirection.CONTROL_TX))
        controls=DeviceControls(self.bus,self.states,relay)
        with self.assertRaises(RuntimeError): controls.execute(['led','2','on'])
