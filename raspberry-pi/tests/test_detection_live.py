import ast
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import threading
import unittest
from unittest.mock import patch
from test_event_poll import Bus, response
from audio import AudioManager
from railing import RailingManager
from plc.events import EventPoller
from protocol import Frame, Node, Service, Command


class LiveCountTests(unittest.TestCase):
    def setUp(self):
        self.bus=Bus();self.rails=RailingManager();self.audio=AudioManager(self.bus,self.rails)
        self.updates=[];self.events=[]
        self.poller=EventPoller(self.bus,self.rails,self.audio,[1,2],self.events.append,
                                count_update=lambda *args:self.updates.append(args))

    def reply(self, rail=1, source=1, count=7, token=b'abcd', outputs=b'\x00\x01'):
        self.poller.pending=(1,b'abcd');self.poller.received=False
        return Frame(rail,Node.P4,Node.PI,Service.SYSTEM,Command.EVENT_REPLY,
                     token+bytes(10)+outputs+bytes([source])+count.to_bytes(4,'big'))

    def test_correlated_total_reset_and_unsigned_range(self):
        for value in (7,0,0xffffffff):
            self.poller.handle_frame(self.reply(count=value))
            self.assertTrue(self.poller.received)
        self.assertEqual(self.updates,[(1,1,7),(1,1,0),(1,1,0xffffffff)])
        self.assertEqual(self.events,[])

    def test_bad_source_token_rail_and_boolean_are_ignored(self):
        for args in ({'source':2},{'token':b'xxxx'},{'rail':2},{'outputs':b'\x02\x00'}):
            self.poller.handle_frame(self.reply(**args));self.assertFalse(self.poller.received)
        self.assertEqual(self.updates,[])

    def test_capability_probe_falls_back_once_for_old_firmware(self):
        def answer(request):
            if len(request.payload)==8:self.poller.handle_frame(response(request))
        self.bus.callback=answer;self.poller.reply_timeout=.001
        self.poller.poll_once(1)
        self.assertEqual([len(f.payload) for f,_ in self.bus.sent],[9,8])
        self.assertEqual(len(self.events),1)
        self.poller.poll_once(1)
        self.assertEqual([len(f.payload) for f,_ in self.bus.sent],[9,8,8])

    def test_new_protocol_still_prioritizes_retained_emergency(self):
        self.bus.callback=lambda req:self.poller.handle_frame(response(req))
        self.poller.poll_once(1);self.poller.poll_once(1)
        self.assertEqual([len(f.payload) for f,_ in self.bus.sent],[9,9])
        self.assertEqual(len(self.events),1);self.assertEqual(self.updates,[])

    def test_publisher_coalesces_unchanged_counts_but_delivers_resets_and_reconnect(self):
        # Execute the actual callback without opening the hardware main loop.
        tree=ast.parse((Path(__file__).parents[1]/'main.py').read_text())
        func=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='publish_count')
        connected=threading.Event();connected.set();messages=[];clock=[1]
        scope={'count_last':{},'publisher':SimpleNamespace(connected=connected,publish=messages.append),
               'time':SimpleNamespace(monotonic=lambda:clock[0])}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[func],type_ignores=[])),'callback','exec'),scope)
        send=scope['publish_count']
        send(1,0,4);send(1,0,4);self.assertEqual(len(messages),1)
        send(1,0,0);self.assertEqual(messages[-1]['count'],0)
        clock[0]+=5;send(1,0,0);self.assertEqual(len(messages),3)
        connected.clear();send(1,0,0);connected.set();send(1,0,0)
        self.assertEqual(len(messages),4)
        self.assertEqual(messages[-1]['type'],'detection_state')
