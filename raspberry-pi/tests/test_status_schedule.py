import sys,types,unittest,threading
from unittest.mock import patch
from pathlib import Path
import importlib.util
class SchedulingTests(unittest.TestCase):
 def make(self):
  with patch.dict(sys.modules,{'music_info':types.SimpleNamespace(request=None),'protocol':types.SimpleNamespace(Service=None,Node=None,Command=None)}):
   spec=importlib.util.spec_from_file_location('isolated_status',Path(__file__).parents[1]/'status_sync.py')
   module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
  connected=threading.Event();connected.set()
  s=module.StatusSync(None,None,[1],types.SimpleNamespace(connected=connected))
  s.demand({'version':1,'rails':[1]});return s
 def test_refresh_wakes_and_does_not_wait_five_seconds(self):
  s=self.make();s.due[1]=float('inf');s.refresh(1)
  self.assertTrue(s.wake.is_set());calls=[];s.sample=lambda r:calls.append(r) or True
  s._poll_once();self.assertEqual([1],calls)
 def test_refresh_during_query_survives(self):
  s=self.make();s.sample=lambda r:s.refresh(r) or True
  s._poll_once();self.assertEqual(0,s.due[1]);self.assertIn(1,s.pending)
 def test_busy_immediate_query_retries_without_five_second_delay(self):
  s=self.make();s.refresh(1);s.sample=lambda r:False
  import time
  before=time.monotonic();s._poll_once()
  self.assertLess(s.due[1]-before,1);self.assertIn(1,s.pending)
 def test_disconnect_clears_priority(self):
  s=self.make();s.refresh(1);s.disconnect();self.assertFalse(s.pending)
if __name__=='__main__':unittest.main()
