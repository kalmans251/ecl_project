import tempfile,unittest
from datetime import datetime,timedelta,timezone
from uuid import uuid4
from protocol import Command,Frame,Node,Service
from device_control import DeviceControls
from railing import RailingManager
from voice import VoiceRelay
from music_remote import MusicRemote
class CountControlsTests(unittest.TestCase):
 def setUp(self):
  self.frames=[];self.detail=bytes.fromhex('01010000007b')
  class Bus: pass
  self.bus=Bus();self.bus.send_frame=self.send
  rails=RailingManager();self.controls=DeviceControls(self.bus,rails,VoiceRelay(self.bus,rails),ack_timeout=.01)
 def send(self,f):
  self.frames.append(f)
  self.controls.handle_frame(Frame(f.railing_id,Node.P4,Node.PI,f.service,Command.APPLY_RESULT,f.payload[:5]+b'\x00'+self.detail))
 def test_count_query_and_reset_confirmed_wire(self):
  result=self.controls.execute(['detection','1','count'],structured=True)
  self.assertFalse(result['device_application_confirmed'])
  self.assertEqual(result['steps'][0]['data'],'01010000007b')
  self.assertEqual(self.frames[-1].payload[4:],bytes([Command.STATUS_REQUEST]))
  self.detail=bytes.fromhex('010100000000')
  result=self.controls.execute(['detection','1','reset'],structured=True)
  self.assertTrue(result['device_application_confirmed'])
  self.assertEqual(self.frames[-1].payload[4:],bytes([Command.DETECTION_RESET]))
  self.assertIn('count=0',self.controls.execute(['detection','1','count']))
 def test_bad_schema_or_nonzero_reset_is_not_confirmed_or_retried(self):
  for detail in ['00','020100000000','010200000000','010100000001']:
   self.detail=bytes.fromhex(detail);before=len(self.frames)
   with self.assertRaises(TimeoutError):self.controls.execute(['detection','1','reset'])
   self.assertEqual(len(self.frames),before+1)
 def test_web_reset_is_not_replayed_after_pi_restart(self):
  self.detail=bytes.fromhex('010000000000')
  with tempfile.TemporaryDirectory() as d:
   m=dict(version=1,type='command',message_id=str(uuid4()),operation='detection.reset',value=None,railing_id=1,expires_at=(datetime.now(timezone.utc)+timedelta(seconds=14)).isoformat())
   result=MusicRemote(self.controls,[1],d+'/journal').handle(m)
   self.assertEqual(result['status'],'APPLIED')
   self.assertEqual(MusicRemote(self.controls,[1],d+'/journal').handle(m),result)
   self.assertEqual(len(self.frames),1)
