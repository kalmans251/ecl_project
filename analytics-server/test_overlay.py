import unittest
from overlay import snapshot
class OverlayTests(unittest.TestCase):
    def test_tracks_do_not_share_age_and_are_normalized(self):
        rows=[(1,(10,20,50,90)),(2,(20,10,80,70))]
        tracks={1:{'ages':[27,29]},2:{'ages':[]}}
        result=snapshot(rows,tracks,100,100,'1:4','ready')
        self.assertEqual(result['people'][0]['age'],28)
        self.assertEqual(result['people'][0]['box'],[.1,.2,.5,.9])
        self.assertIsNone(result['people'][1]['age'])
        self.assertEqual(result['people'][1]['state'],'pending')
        self.assertNotIn('age_sent',tracks[1])
    def test_bounded_and_unknown(self):
        rows=[(n,(0,0,10,10)) for n in range(100)]
        self.assertEqual(len(snapshot(rows,{},100,100,'1:1','disabled')['people']),20)
        self.assertEqual(snapshot([(1,(0,0,10,10))],{1:{'ages':[30],'age_sent':True}},100,100,'1:1','ready')['people'][0]['state'],'unknown')
        self.assertEqual(snapshot([],{},100,100,'1:2','ready')['people'],[])
if __name__=='__main__': unittest.main()
