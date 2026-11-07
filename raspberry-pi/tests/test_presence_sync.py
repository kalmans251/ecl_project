import unittest
from unittest.mock import patch
from datetime import datetime,timedelta,timezone
from presence_sync import PresenceUpdates

class PresenceTests(unittest.TestCase):
 def message(self,rail=1):
  now=datetime.now(timezone.utc)
  return dict(version=1,type='cctv.presence',railing_id=rail,
              observed_at=now.isoformat(),expires_at=(now+timedelta(seconds=3)).isoformat())
 def test_coalesces_and_uses_presence_not_new_person(self):
  p=PresenceUpdates(None,[1]);p.offer(self.message());p.offer(self.message())
  with patch('presence_sync.request') as send:
   p.step(lambda:True);p.step(lambda:True)
   self.assertEqual(send.call_count,1)
   self.assertEqual(send.call_args.args[3],bytes([4]))
   self.assertTrue(send.call_args.kwargs['background'])
 def test_expired_wrong_rail_and_disconnection_never_send(self):
  p=PresenceUpdates(None,[1]);old=self.message()
  old['observed_at']=(datetime.now(timezone.utc)-timedelta(seconds=10)).isoformat()
  old['expires_at']=(datetime.now(timezone.utc)-timedelta(seconds=7)).isoformat()
  p.offer(old);p.offer(self.message(2))
  self.assertEqual(p.pending,{})
  p.offer(self.message())
  with patch('presence_sync.request') as send:
   p.step(lambda:False);send.assert_not_called()
 def test_waiting_hint_expiry_and_busy_are_not_replayed(self):
  p=PresenceUpdates(None,[1]);p.offer(self.message())
  with patch('presence_sync.time.monotonic',return_value=10**20),patch('presence_sync.request') as send:
   p.step(lambda:True);send.assert_not_called()
  p.offer(self.message())
  with patch('presence_sync.request',side_effect=RuntimeError('PLC busy')) as send:
   p.step(lambda:True);p.step(lambda:True)
   self.assertEqual(send.call_count,1)
