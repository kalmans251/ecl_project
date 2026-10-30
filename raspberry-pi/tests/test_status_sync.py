import tempfile
from emergency_outbox import EmergencyOutbox
import threading
import unittest
from types import SimpleNamespace
from status_sync import StatusSync,decode
from device_control import DeviceControls
from railing import RailingManager
from voice import VoiceRelay
from protocol import Frame,Node,Service,Command

DATA=bytes([1,1,1,1,2,3,0,1,1,1,2,0,0,0,7,0])
class StatusTests(unittest.TestCase):
 def setUp(self):
  self.messages=[];self.connected=threading.Event();self.connected.set()
  lock=threading.Lock()
  self.bus=SimpleNamespace(transaction=lambda:lock,sent=[])
  self.states=RailingManager();self.controls=DeviceControls(self.bus,self.states,VoiceRelay(self.bus,self.states))
  self.audio=SimpleNamespace(_control_lock=threading.Lock(),_keepalive_due=threading.Event())
  self.publisher=SimpleNamespace(connected=self.connected,publish=self.messages.append)
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.outbox=EmergencyOutbox(self.temp.name+"/events.db")
  self.sync=StatusSync(self.controls,self.audio,[1,2],self.publisher,self.outbox)
  self.sync.demand(dict(version=1,rails=[1]))
  def send(f):
   self.bus.sent.append(f)
   self.assertEqual((Service.SYSTEM,Command.APPLY,b'\x04'),(f.service,f.command,f.payload[5:]))
   for rail,token in [(2,f.payload[:4]),(1,bytes(4))]:
    self.controls.handle_frame(Frame(rail,Node.P4,Node.PI,Service.SYSTEM,Command.APPLY_RESULT,token+f.payload[4:5]+b'\x00'+DATA))
    self.assertIsNone(self.controls.result)
   self.controls.handle_frame(Frame(1,Node.P4,Node.PI,Service.SYSTEM,Command.APPLY_RESULT,f.payload[:5]+b'\x00'+DATA))
  self.bus.send_frame=send
 def test_real_correlated_query_and_truthful_fields(self):
  self.assertTrue(self.sync.sample(1));s=self.messages[0]['state']
  self.assertEqual('weather',s['led']);self.assertTrue(s['sleep_active']);self.assertEqual(7,s['detection_count'])
  self.assertNotIn('volume',s);self.assertNotIn('battery_percent',s)
 def test_old_p4_fallback_is_cached_and_reprobed_after_disconnect(self):
  versions=[]
  def send(f):
   versions.append(f.payload[-1])
   status=b'\x01' if f.payload[-1]>1 else b'\x00'
   data=b'\x00' if status==b'\x01' else DATA
   self.controls.handle_frame(Frame(1,Node.P4,Node.PI,Service.SYSTEM,Command.APPLY_RESULT,f.payload[:5]+status+data))
  self.bus.send_frame=send
  self.assertTrue(self.sync.sample(1));self.assertTrue(self.sync.sample(1))
  self.assertEqual([4,3,2,1,1],versions)
  self.sync.disconnect();self.sync.demand(dict(version=1,rails=[1]))
  self.assertTrue(self.sync.sample(1));self.assertEqual([4,3,2,1],versions[-4:])
 def test_no_network_or_busy_control_or_call_does_not_poll(self):
  self.connected.clear();self.assertFalse(self.sync.sample(1));self.connected.set()
  with self.audio._control_lock:self.assertFalse(self.sync.sample(1))
  self.audio._keepalive_due.set();self.assertFalse(self.sync.sample(1));self.audio._keepalive_due.clear()
  self.states.reserve_call(1);self.assertFalse(self.sync.sample(1));self.assertEqual([],self.bus.sent)
 def test_old_firmware_and_invalid_samples_are_not_current_telemetry(self):
  for data in (b'\x01',DATA[:-1],bytes([2])+DATA[1:]):
   with self.assertRaises(ValueError):decode(data)
  self.bus.send_frame=lambda f:self.controls.handle_frame(Frame(1,Node.P4,Node.PI,Service.SYSTEM,Command.APPLY_RESULT,f.payload[:5]+b'\x01\x00'))
  self.assertFalse(self.sync.sample(1));self.assertEqual([],self.messages)

 def test_alarm_transition_is_separate_and_no_plc_poll(self):
  self.sync.emergency(1);self.assertEqual([],self.messages)
  self.states.emergency_start(1,1,123);self.sync.emergency(1);self.sync.emergency(1)
  start=self.outbox.drain()[0];self.assertTrue(start['state']['active'])
  self.outbox.acknowledge(dict(version=2,type='emergency_ack',event_id=start['event_id'],railing_id=1))
  self.states.emergency_stop(1,123);self.sync.emergency(1)
  self.outbox.last=float('-inf');self.assertFalse(self.outbox.drain()[0]['state']['active']);self.assertEqual([],self.bus.sent)

 def test_demand_expiry_and_disconnect_stop_queries(self):
  self.sync.disconnect();self.assertFalse(self.sync.sample(1))
  self.sync.demand(dict(version=1,rails=[2,99]));self.assertFalse(self.sync.sample(1))
  self.sync.demand(dict(version=1,rails=[1]));self.sync.wanted[1]=0
  self.assertFalse(self.sync.sample(1));self.assertEqual([],self.bus.sent)
  self.sync.demand(dict(version=1,rails=[1]));self.assertTrue(self.sync.sample(1))

 def test_refresh_only_prioritizes_current_viewers(self):
  self.sync.due={1:999,2:999};self.sync.refresh(2);self.assertEqual(999,self.sync.due[2])
  self.sync.refresh(1);self.assertEqual(0,self.sync.due[1])
  self.sync.disconnect();self.sync.due[1]=999
  self.sync.demand(dict(version=1,rails=[1]));self.assertEqual(0,self.sync.due[1])

class EnergyTests(unittest.TestCase):
 def sample(self,flags=31,mv=13200):
  return bytes([2])+DATA[1:]+bytes([flags])+mv.to_bytes(2,'big')+(13200).to_bytes(2,'big')+(13000).to_bytes(2,'big')+(500).to_bytes(4,'big',signed=True)+(-100).to_bytes(4,'big',signed=True)
 def test_scaled_signed_energy_and_estimate(self):
  s=decode(self.sample());self.assertEqual(70,s['battery_percent']);self.assertTrue(s['battery_estimated'])
  self.assertEqual(13.2,s['battery_voltage']);self.assertEqual(6.6,s['left_watt']);self.assertEqual(-1.3,s['right_watt'])
 def test_missing_sensor_is_not_zero(self):
  s=decode(self.sample(0));self.assertNotIn('battery_percent',s);self.assertNotIn('left_watt',s)
  s=decode(self.sample(1));self.assertEqual(13.2,s['left_voltage']);self.assertNotIn('left_current',s)
 def test_reject_invalid_energy(self):
  for d in (self.sample()[:-1],self.sample(32),self.sample(4),self.sample(mv=20000)):
   with self.assertRaises(ValueError):decode(d)
 def test_curve_bounds_and_monotonic(self):
  from status_sync import estimate_percent
  values=[estimate_percent(v/100) for v in range(800,1601)]
  self.assertEqual(values,sorted(values));self.assertEqual(0,values[0]);self.assertEqual(100,values[-1])

class LedStatusTests(unittest.TestCase):
 def test_version4_reports_sequence_selection_and_interval(self):
  base=bytes([4])+DATA[1:]+bytes(15)+bytes([9,2,12])
  state=decode(base)
  self.assertEqual(9,state['led_basic_pattern']);self.assertEqual(2,state['led_music_pattern']);self.assertEqual(12,state['led_sequence_seconds'])
  for index,value in ((31,10),(32,3),(33,0),(33,121)):
   sample=bytearray(base);sample[index]=value
   with self.assertRaises(ValueError):decode(sample)
