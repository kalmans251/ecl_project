import json
import tempfile
import time
import unittest
from pathlib import Path
from datetime import datetime, timezone
from uuid import uuid4
from contextlib import nullcontext
from monitoring import CallGateway
from railing import RailingManager

class Socket:
    def __init__(self): self.sent=[]
    def send(self,s): self.sent.append(json.loads(s))
class Voice:
    def control_transition(self): return nullcontext()
    def state_changed(self): pass
class Audio:
    def __init__(self, states): self.states=states; self.starts=0
    def start_call(self,rid):
        self.starts+=1; self.states.reserve_call(rid)
        sid=self.states.snapshot(rid)['call']['session_id']
        self.states.call_started(rid,0,1,session_id=sid);return True
    def end_call(self,rid): return self.states.call_ended(rid)
    def set_direction(self,rid,d): self.states.call_direction_changed(rid,d)

class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.states=RailingManager();self.audio=Audio(self.states)
        self.path=Path(self.tmp.name)/'monitor.json'
        self.g=CallGateway(self.audio,self.states,Voice(),'ws://127.0.0.1/ws/gateways/g1','x'*32,self.path,[1,2])
        self.g.socket=Socket();self.cid=str(uuid4())
    def message(self,op='call.start'):
        return dict(version=1,type='command',message_id=str(uuid4()),call_id=self.cid,railing_id=1,
                    operation=op,expires_at=datetime.fromtimestamp(time.time()+15,timezone.utc).isoformat())
    def run_command(self,m):
        self.g.accept(m);self.g.execute(self.g.jobs.get_nowait())
    def test_applied_dedup_fault_and_confirmed_end(self):
        m=self.message();self.run_command(m);self.g.accept(m)
        self.assertEqual(self.audio.starts,1);self.assertEqual(self.g.socket.sent[-1]['status'],'APPLIED')
        self.g.publish();snapshot=self.g.socket.sent[-1]
        self.assertEqual(len(snapshot),9);self.assertEqual(snapshot['phase'],'active')
        self.states.call_direction_unknown(1,snapshot['session_id'],error='S3_TIMEOUT')
        self.g.publish();self.assertEqual(self.g.socket.sent[-1]['error'],'S3_TIMEOUT')
        self.run_command(self.message('call.end'));self.g.publish()
        self.assertEqual(self.g.socket.sent[-1]['phase'],'ended')
        # Durable terminal evidence remains reportable after Pi restart.
        g=CallGateway(Audio(RailingManager()),RailingManager(),Voice(),self.g.url,'x'*32,self.path,[1])
        g.socket=Socket();g.publish();self.assertEqual(g.socket.sent[-1]['phase'],'ended')
    def test_received_command_is_not_replayed_after_restart(self):
        m=self.message();self.g.accept(m)
        g=CallGateway(self.audio,self.states,Voice(),self.g.url,'x'*32,self.path,[1]);g.socket=Socket()
        g.accept(m);self.assertEqual(g.socket.sent[-1]['status'],'FAILED');self.assertTrue(g.jobs.empty())
    def test_no_end_is_fabricated_from_idle_or_missing_journal(self):
        self.run_command(self.message('call.end'))
        self.assertEqual(self.g.socket.sent[-1]['status'],'FAILED');self.g.publish()
        self.assertNotEqual(self.g.socket.sent[-1].get('phase'),'ended')
    def test_expiry_foreign_rail_and_payload_rejected(self):
        m=self.message();m['expires_at']=datetime.fromtimestamp(time.time()-1,timezone.utc).isoformat()
        self.g.accept(m);self.assertEqual(self.g.socket.sent[-1]['status'],'EXPIRED')
        m=self.message();m['railing_id']=3;self.g.accept(m)
        self.assertEqual(self.g.socket.sent[-1]['status'],'FAILED');self.assertEqual(self.audio.starts,0)
    def test_disconnect_stops_active_and_inflight_calls(self):
        self.run_command(self.message());self.g.disconnected()
        self.assertEqual(self.states.snapshot(1)['call']['phase'],'unknown')
        self.assertIsNone(self.states.get_call_direction(1))
        sid=self.states.snapshot(1)['call']['session_id']
        self.assertFalse(self.states.call_started(1,0,1,session_id=sid))
        self.assertFalse(self.states.call_direction_changed(1,2,session_id=sid))
    def test_disconnect_during_start_cannot_resume_keepalive(self):
        start=self.audio.start_call
        def interrupted(rid):
            result=start(rid);self.g.disconnected();return result
        self.audio.start_call=interrupted
        self.run_command(self.message())
        self.assertEqual(self.states.snapshot(1)['call']['phase'],'unknown')
    def test_queued_request_is_not_executed_on_a_new_connection(self):
        m=self.message();self.g.accept(m);job=self.g.jobs.get_nowait()
        self.g.disconnected();self.g.socket=Socket();self.g.execute(job)
        self.assertEqual(self.audio.starts,0)
        self.assertEqual(self.g.socket.sent[-1]['status'],'FAILED')
    def test_prior_end_is_not_assigned_to_a_new_call(self):
        self.run_command(self.message());self.run_command(self.message('call.end'))
        old=self.states.snapshot(1)['call']['session_id'];self.cid=str(uuid4())
        self.g.data['binding']={'call_id':self.cid,'railing_id':1,'session_id':0,'previous_session':old}
        n=len(self.g.socket.sent);self.g.publish();self.assertEqual(len(self.g.socket.sent),n)
    def test_remote_plaintext_rejected(self):
        with self.assertRaises(ValueError):
            CallGateway(self.audio,self.states,Voice(),'ws://example.com/ws/gateways/g1','x'*32,self.path,[1])
