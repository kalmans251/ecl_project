import tempfile, unittest
from emergency_outbox import EmergencyOutbox
class OutboxTests(unittest.TestCase):
 def test_restart_order_duplicates_and_exact_receipt(self):
  with tempfile.TemporaryDirectory() as d:
   p=d+'/events.db';o=EmergencyOutbox(p)
   o.record(1,(True,9));o.record(1,(True,9));o.record(1,(False,9))
   first=o.drain()[0];o=EmergencyOutbox(p)
   self.assertEqual(first,o.drain()[0])
   ack=dict(version=2,type='emergency_ack',event_id=first['event_id'],railing_id=2)
   o.acknowledge(ack);o.last=float('-inf');self.assertEqual(first,o.drain()[0])
   ack['railing_id']=1;o.acknowledge(ack);o.last=float('-inf');end=o.drain()[0]
   self.assertFalse(end['state']['active']);self.assertGreater(end['observed_at'],first['observed_at'])
   o.acknowledge(ack);o.last=float('-inf');self.assertEqual(end,o.drain()[0])
   o.acknowledge(dict(ack,event_id=end['event_id']));o.last=float('-inf');self.assertEqual([],o.drain())
