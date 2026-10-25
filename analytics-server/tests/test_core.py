from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import Entries

class EntriesTest(unittest.TestCase):
 def test_stable_entry_once_and_keep_on_age_timeout(self):
  now=[0.];e=Entries('camera-a',lambda:now[0])
  self.assertEqual(e.update([1]),[]);now[0]=.1;self.assertEqual(e.update([1]),[])
  now[0]=.2;events=e.update([1]);self.assertEqual(len(events),1)
  for i in range(10):now[0]+=.1;self.assertEqual(e.update([1]),[])
  now[0]=1.8;age=e.age_events();self.assertEqual(age[0]['age_group'],'keep');self.assertEqual(age[0]['event_id'],events[0]['event_id'])
  self.assertEqual(e.age_events(),[])
 def test_age_belongs_to_camera_track_generation(self):
  now=[0.];a=Entries('a',lambda:now[0]);b=Entries('b',lambda:now[0])
  for _ in range(3):a.update([1]);b.update([1]);now[0]+=.1
  event=a.tracks[1]['event'];self.assertNotEqual(event['event_id'],b.tracks[1]['event']['event_id'])
  a.age(1,'wrong',22);self.assertEqual(a.tracks[1]['ages'],[])
  a.age(1,event['event_id'],22);a.age(1,event['event_id'],24)
  self.assertEqual(a.age_events()[0]['age_group'],'20')
  now[0]=4;a.update([1]);a.age(1,event['event_id'],22);self.assertEqual(a.tracks[1]['ages'],[])
 def test_intermittent_detections_do_not_enter(self):
  now=[0.];e=Entries('a',lambda:now[0])
  for _ in range(5):self.assertEqual(e.update([1]),[]);now[0]+=1

if __name__=='__main__':unittest.main()
