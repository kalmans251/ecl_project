import asyncio
import json
import tempfile
import threading
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from music_remote import MusicRemote
from music_sync import MusicPublisher
from test_device_control import Bus
from device_control import DeviceControls
from railing import RailingManager
from voice import VoiceRelay

class CctvRemoteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bus = Bus()
        states = RailingManager()
        self.controls = DeviceControls(self.bus, states, VoiceRelay(self.bus, states), ack_timeout=.01)
        self.bus.controls = self.controls
        self.path = self.tmp.name+'/requests.db'
        self.remote = MusicRemote(self.controls, [1], self.path)

    def event(self, kind='enter'):
        now = datetime.now(timezone.utc)
        m = dict(version=1, type='cctv.'+kind, camera_id='cctv01',
                 message_id=str(uuid.uuid4()), railing_id=1, event_seq=123,
                 observed_at=now.isoformat(), expires_at=(now+timedelta(seconds=5)).isoformat())
        if kind == 'age': m['age_group']='keep'
        return m

    def test_enter_age_wire_ack_and_restart_dedup(self):
        for kind, payload in [('enter', b'\x01\x00\x00\x00\x7b'), ('age', b'\x02\x00\x00\x00\x7b\xff')]:
            m=self.event(kind)
            result=self.remote.handle(m)
            self.assertEqual(result, dict(version=1,type='ack',message_id=m['message_id'],status='PLC_SENT'))
            self.assertEqual(self.bus.sent[-1].payload[5:],payload)
            count=len(self.bus.sent)
            self.assertEqual(MusicRemote(self.controls,[1],self.path).handle(m),result)
            self.assertEqual(len(self.bus.sent),count)
            self.assertEqual(self.remote.handle(dict(m,event_seq=124))['status'],'FAILED')

    def test_invalid_expired_disconnected_and_busy_no_send(self):
        for fields in [dict(railing_id=2),dict(event_seq=-1),dict(event_seq=True),dict(camera_id='../x'),dict(age_group='20'),dict(observed_at='bad')]:
            self.assertEqual(self.remote.handle(dict(self.event(),**fields))['status'],'FAILED')
        m=self.event(); now=datetime.now(timezone.utc); m['observed_at']=(now-timedelta(seconds=6)).isoformat();m['expires_at']=(now-timedelta(seconds=1)).isoformat()
        self.assertEqual(self.remote.handle(m)['status'],'EXPIRED')
        self.assertEqual(self.remote.handle(self.event(),lambda:False)['status'],'FAILED')
        self.remote.lock.acquire()
        try:self.assertEqual(self.remote.handle(self.event())['status'],'BUSY')
        finally:self.remote.lock.release()
        self.assertEqual(self.bus.sent,[])

    def test_timeout_not_success_and_no_replay(self):
        m=self.event()
        with patch.object(self.controls,'execute',side_effect=TimeoutError()) as send:
            self.assertEqual(self.remote.handle(m)['status'],'FAILED')
            self.assertEqual(self.remote.handle(m)['status'],'FAILED')
            send.assert_called_once()

    def test_websocket_routes_event_to_plc(self):
        async def run():
            pub=MusicPublisher('wss://example.org/ws/gateways/gateway-01','secret',self.remote)
            sent=[]; incoming=asyncio.Queue();await incoming.put(json.dumps(self.event()))
            class Socket:
                async def recv(self):return await incoming.get()
                async def send(self,raw):sent.append(json.loads(raw))
            alive=threading.Event();alive.set()
            task=asyncio.create_task(pub._connection(Socket(),alive))
            try:
                for _ in range(100):
                    if sent:break
                    await asyncio.sleep(.01)
                self.assertEqual(sent[0]['status'],'PLC_SENT')
                self.assertEqual(len(sent[0]),4)
                self.assertEqual(len(self.bus.sent),1)
            finally:
                pub.stop.set();task.cancel()
                await asyncio.gather(task,return_exceptions=True)
        asyncio.run(run())
