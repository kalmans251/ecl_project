import tempfile,unittest,threading
from datetime import datetime,timedelta,timezone
from uuid import uuid4
from music_remote import MusicRemote
from control_remote import parts
from test_device_control import Bus
from device_control import DeviceControls
from railing import RailingManager
from voice import VoiceRelay

class RemoteControlsTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.bus=Bus();rails=RailingManager();self.controls=DeviceControls(self.bus,rails,VoiceRelay(self.bus,rails),ack_timeout=.01)
  self.bus.controls=self.controls;self.remote=MusicRemote(self.controls,[1,2],self.tmp.name+'/journal')
 def message(self,op,value=None,rail=1):
  return dict(version=1,type='command',message_id=str(uuid4()),operation=op,value=value,railing_id=rail,
              expires_at=(datetime.now(timezone.utc)+timedelta(seconds=14)).isoformat())
 def test_confirmed_power_two_steps_and_restart_dedup(self):
  m=self.message('power','ac');r=self.remote.handle(m)
  self.assertEqual(r['type'],'control_result');self.assertEqual(r['status'],'APPLIED');self.assertEqual(len(r['data']['steps']),2)
  before=len(self.bus.sent);again=MusicRemote(self.controls,[1,2],self.tmp.name+'/journal')
  self.assertEqual(again.handle(m),r);self.assertEqual(len(self.bus.sent),before)
  self.assertEqual(again.handle(dict(m,railing_id=2))['status'],'FAILED')
 def test_policy_and_query_not_application(self):
  for op,value in [('music.start',None),('music.mode','shuffle'),('query','s3')]:
   result=self.remote.handle(self.message(op,value));self.assertEqual(result['status'],'COMPLETED')
   self.assertFalse(result['data']['device_application_confirmed'])
 def test_deadline_between_power_steps_prevents_start_and_unknown_is_not_replayed(self):
  count=0
  def connected():
   nonlocal count
   count+=1;return count<3
  m=self.message('power','battery');result=self.remote.handle(m,connected)
  self.assertEqual(result['status'],'UNKNOWN');self.assertEqual(len(self.bus.sent),1)
  self.assertEqual(self.remote.handle(m),result);self.assertEqual(len(self.bus.sent),1)
 def test_mapping_and_validation(self):
  self.assertEqual(parts('led.basic_pattern','5',2),['led','2','basic','6'])
  self.assertEqual(parts('led.music_pattern','2',1),['led','1','music','3'])
  for op,value in [('volume','101'),('music.stop','x'),('led.basic_pattern','6'),('power','ac; quit'),('query','pi')]:
   self.assertEqual(self.remote.handle(self.message(op,value))['status'],'FAILED')
  self.assertEqual(self.bus.sent,[])
 def test_unknown_call_blocks_controls(self):
  self.controls.voice.control_paused=lambda:True
  self.assertEqual(self.remote.handle(self.message('projector','on'))['status'],'UNKNOWN')
  self.assertEqual(self.bus.sent,[])
 def test_guard_after_bus_lock(self):
  active=True
  class Transaction:
   def __enter__(self):
    nonlocal active
    active=False
   def __exit__(self,*args):pass
  self.bus.transaction=Transaction
  self.assertEqual(self.remote.handle(self.message('led','off'),lambda:active)['status'],'UNKNOWN')
  self.assertEqual(self.bus.sent,[])
