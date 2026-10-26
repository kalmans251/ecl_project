import threading,time,unittest
from types import SimpleNamespace
from protocol import Frame,Node,Service,Command
from radar_sync import RadarSync,decode
from music_sync import MusicPublisher

def payload(token=b'abcd',detail=True,count=1,valid=1,age=0,source=2):
 p=token+bytes([1,source,valid,count])+bytes([0,0,0,1])+age.to_bytes(2,'big')+bytes([detail])
 return p+(b'\xfc\x18\x07\xd0'*count if detail and valid else b'')

class RadarTests(unittest.TestCase):
 def setUp(self):
  self.sent=[];lock=threading.RLock()
  self.bus=SimpleNamespace(transaction=lambda:lock,send_frame=self.send)
  self.states={}
  self.audio=SimpleNamespace(_control_lock=threading.Lock(),_keepalive_due=threading.Event())
  self.radar=RadarSync(self.bus,SimpleNamespace(lock=threading.Lock()),self.audio,
    SimpleNamespace(snapshot=lambda:self.states),[1,2],lambda x:None)
  self.radar.demand(dict(version=1,rails=[1,2]))
 def send(self,f):
  self.sent.append(f)
  # Wrong rail/token must not satisfy this request.
  self.radar.handle_frame(Frame(2,Node.P4,Node.PI,Service.RADAR,Command.STATUS_RESPONSE,payload(f.payload[:4],bool(f.payload[4]))))
  self.assertIsNone(self.radar.result)
  self.radar.handle_frame(Frame(1,Node.P4,Node.PI,Service.RADAR,Command.STATUS_RESPONSE,payload(f.payload[:4],bool(f.payload[4]))))
 def test_decode_and_bounds(self):
  self.assertEqual(decode(payload(),True)['targets'],[{'x':-1.,'y':2.}])
  self.assertEqual(decode(payload(detail=False),False)['targets'],[])
  for p in (payload()[:-1],payload(age=1501),payload(source=0),payload(valid=0)):
   with self.assertRaises(ValueError):decode(p,True)
 def test_correlated_query_and_no_people_reply(self):
  self.assertTrue(self.radar.query(1,True)['available'])
  self.assertEqual(len(self.sent),1)
  p=payload(count=0);self.assertEqual(decode(p,True)['count'],0)
 def test_call_busy_and_expired_demand_never_send(self):
  self.states[1]={'call':{'active':True,'phase':'active'},'emergency':{'active':False}}
  self.assertEqual(self.radar.query(1,True)['reason'],'call_or_emergency')
  self.states.clear();self.radar.disconnect()
  self.assertIsNone(self.radar.query(1,True));self.assertEqual(self.sent,[])
 def test_control_lock_skips_and_timeout_is_not_zero(self):
  self.audio._control_lock.acquire()
  self.assertIsNone(self.radar.query(1,True));self.audio._control_lock.release()
  self.bus.send_frame=lambda f:None
  result=self.radar.query(1,True)
  self.assertEqual(result,{'available':False,'reason':'timeout'})
 def test_music_and_radar_do_not_overwrite_each_other(self):
  p=MusicPublisher('wss://example.test/ws/gateways/g','token')
  p.publish(dict(type='music_state',railing_id=1))
  p.publish(dict(type='radar_state',railing_id=1))
  self.assertEqual({m['type'] for m in p.drain()},{'music_state','radar_state'})
