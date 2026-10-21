import threading
import unittest
from audio import AudioManager
from railing import RailingManager
from plc.events import EventPoller
from protocol import Frame, Node, Service, Command, AudioDirection

class Bus:
    def __init__(self):
        self.sent=[];self.lock=threading.RLock();self.callback=lambda f: None
    def transaction(self): return self.lock
    def send_frame(self,f):
        self.sent.append((f,{}));self.callback(f)
    def send_control_frame(self,f,**options):
        self.sent.append((f,options));self.callback(f)

def response(f, event_id=9, token=None):
    payload=(f.payload[:4] if token is None else token)+event_id.to_bytes(4,'big')+bytes(4)
    payload+=bytes([Service.EMERGENCY,Command.START,1,0,0,0,123]) if event_id else bytes(2)
    return Frame(f.railing_id,Node.P4,Node.PI,Service.SYSTEM,Command.EVENT_REPLY,payload)

class PollTests(unittest.TestCase):
    def setUp(self):
        self.bus=Bus();self.states=RailingManager();self.audio=AudioManager(self.bus,self.states)
        self.events=[]
        self.poller=EventPoller(self.bus,self.states,self.audio,[1,2],self.events.append)
        self.bus.callback=lambda f:self.poller.handle_frame(response(f))

    def test_endpoint_fault_mutes_until_confirmed_end(self):
        from test_call_start import event
        from protocol import AudioEvent, AudioDataType
        self.states.reserve_call(1)
        sid=self.states.snapshot(1)['call']['session_id']
        self.audio.handle_frame(event(session=sid))
        self.poller.dispatch=self.audio.handle_frame
        fault=bytes([AudioDataType.EVENT,AudioEvent.ENDPOINT_FAILED,0,0])+sid.to_bytes(4,'big')+bytes([Node.S3,3])
        def deliver(request, payload, token):
            envelope=request.payload[:4]+token.to_bytes(4,'big')+bytes(4)+bytes([Service.AUDIO,Command.DATA])+payload
            self.poller.handle_frame(Frame(1,Node.P4,Node.PI,Service.SYSTEM,Command.EVENT_REPLY,envelope))
        stale=fault[:4]+(sid^1).to_bytes(4,'big')+fault[8:]
        self.bus.callback=lambda f:deliver(f,stale,90)
        self.poller.poll_once(1)
        self.assertEqual(self.states.snapshot(1)['call']['phase'],'active')
        self.bus.callback=lambda f:deliver(f,fault,91)
        self.poller.poll_once(1)
        self.assertEqual(self.states.snapshot(1)['call']['phase'],'unknown')
        self.assertIsNone(self.states.get_call_direction(1))
        with self.assertRaises(RuntimeError):self.states.reserve_call(2)
        before=len(self.bus.sent);self.audio.renew_calls();self.assertEqual(len(self.bus.sent),before)
        self.poller.poll_once(1);self.assertEqual(self.poller.ack[1],91)
        self.bus.callback=lambda f:deliver(f,event(kind=AudioEvent.CALL_ENDED,session=sid).payload,92)
        self.poller.poll_once(1);self.assertFalse(self.states.call_pending(1))
        self.states.reserve_call(2)

    def test_delivery_duplicate_and_ack_on_next_poll(self):
        self.assertTrue(self.poller.poll_once(2));self.assertEqual(len(self.events),1)
        self.assertEqual(self.events[0].payload,bytes([1,0,0,0,123]))
        self.poller.poll_once(2);self.assertEqual(len(self.events),1)
        self.assertEqual(self.bus.sent[-1][0].payload[4:],(9).to_bytes(4,'big'))
        self.bus.callback=lambda f:self.poller.handle_frame(response(f,0))
        self.poller.poll_once(2);self.assertEqual(len(self.events),1)

    def test_wrong_token_and_node_are_ignored(self):
        self.bus.callback=lambda f:self.poller.handle_frame(response(f,token=b'xxxx'))
        self.poller.poll_once(2);self.assertEqual(self.events,[])
        def wrong(f):
            r=response(f)
            self.poller.handle_frame(Frame(1,r.src,r.dst,r.service,r.command,r.payload))
        self.bus.callback=wrong
        self.poller.poll_once(2);self.assertEqual(self.events,[])

    def test_field_poll_uses_owner_grant_for_other_target(self):
        self.states.call_started(1,0,AudioDirection.FIELD_TX)
        self.poller.poll_once(2)
        frame,opts=self.bus.sent[-1]
        self.assertEqual(frame.railing_id,2)
        self.assertEqual(opts['grant_railing'],1)
        self.assertEqual(opts['reply_budget_ms'],140)
        self.assertTrue(opts['wait_for_window'])

    def test_pending_call_and_keepalive_take_priority(self):
        self.states.reserve_call(1)
        self.assertFalse(self.poller.poll_once(2));self.assertEqual(self.bus.sent,[])
        self.states.call_ended(1)
        self.audio._keepalive_due.set()
        self.assertFalse(self.poller.poll_once(2));self.assertEqual(self.bus.sent,[])

    def test_handler_failure_does_not_ack_report(self):
        def fail(f): raise RuntimeError('handler failed')
        self.poller.dispatch=fail
        with self.assertRaises(RuntimeError):self.poller.poll_once(2)
        self.assertNotIn(2,self.poller.ack)
        self.poller.dispatch=self.events.append
        self.poller.poll_once(2);self.assertEqual(len(self.events),1)

    def test_unknown_waits_for_lease_then_polls_terminal_end(self):
        from unittest.mock import patch
        from test_call_start import event
        from protocol import AudioEvent
        self.states.reserve_call(1)
        self.states.call_request_failed(1)
        def no_grant(*args, **kwargs): raise TimeoutError('no grant')
        self.bus.send_control_frame=no_grant
        with patch.object(self.audio, 'recovery_delay', return_value=2):
            self.poller.poll_once(1)
        self.assertEqual(self.bus.sent, [])
        self.assertTrue(self.states.call_pending(1))
        def ended(f):
            payload=f.payload[:4]+(99).to_bytes(4,'big')+bytes(4)
            payload+=bytes([Service.AUDIO,Command.DATA])+event(kind=AudioEvent.CALL_ENDED, session=self.states.snapshot(1)["call"]["session_id"]).payload
            self.poller.handle_frame(Frame(1,Node.P4,Node.PI,Service.SYSTEM,Command.EVENT_REPLY,payload))
        self.bus.callback=ended
        self.poller.dispatch=self.audio.handle_frame
        with patch.object(self.audio, 'recovery_delay', return_value=0):
            self.poller.poll_once(1)
        self.assertFalse(self.states.call_pending(1))
        self.assertEqual(self.poller.ack[1],99)

    def test_fragmented_reply_finishing_after_old_deadline_is_accepted(self):
        import time
        from protocol import FrameParser
        parser = FrameParser()
        workers = []
        def send(request):
            raw = response(request).encode()
            def receive():
                time.sleep(0.102)
                # Each chunk goes through the real CRC/length parser.
                for chunk in (raw[:12], raw[12:]):
                    for frame in parser.feed(chunk):
                        self.poller.handle_frame(frame)
                    time.sleep(0.060)
            worker = threading.Thread(target=receive)
            workers.append(worker)
            worker.start()
        self.bus.callback = send
        try:
            self.poller.poll_once(1)
            self.assertEqual(len(self.events), 1)
            self.assertEqual(self.poller.ack[1], 9)
        finally:
            for worker in workers:
                worker.join()

    def test_corrupt_reply_still_not_acknowledged(self):
        from protocol import FrameParser
        def send(request):
            raw = bytearray(response(request).encode())
            raw[-1] ^= 1
            for frame in FrameParser().feed(bytes(raw)):
                self.poller.handle_frame(frame)
        self.bus.callback = send
        self.poller.poll_once(1)
        self.assertEqual(self.events, [])
        self.assertNotIn(1, self.poller.ack)

    def test_grant_budget_still_fits_9600_and_timeout_scales_with_baud(self):
        from plc.events import POLL_REPLY_BUDGET_MS
        self.assertLessEqual(18 * 10 * 1000 / 9600 + 40 + POLL_REPLY_BUDGET_MS, 200)
        self.bus.baudrate = 4800
        slow = EventPoller(self.bus, self.states, self.audio, [1], self.events.append)
        self.assertGreater(slow.reply_timeout, self.poller.reply_timeout)
