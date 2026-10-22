import threading
import unittest
from unittest.mock import patch
from music_sync import MusicSync, MusicPublisher, validate_url
from music_info import status
from test_music_info import Bus
from device_control import DeviceControls
from railing import RailingManager
from voice import VoiceRelay

class MusicSyncTests(unittest.TestCase):
    def test_independent_rails_and_failed_sample(self):
        sync = MusicSync(None, [1, 2])
        with patch('music_sync.status', side_effect=[
                dict(state='playing', filename='one.mp3', position_ms=100),
                dict(state='paused', filename='two.mp3', position_ms=200), TimeoutError()]):
            sync.sample(1); sync.sample(2); sync.sample(1)
        self.assertFalse(sync.snapshot()['1']['state']['available'])
        self.assertEqual(sync.snapshot()['2']['state']['filename'], 'two.mp3')
        self.assertEqual(sync.snapshot()['2']['state']['position_ms'], 200)

    def test_background_yields_busy_bus_and_call_guard(self):
        bus = Bus(); lock = threading.Lock(); bus.transaction = lambda: lock
        rails = RailingManager()
        controls = DeviceControls(bus, rails, VoiceRelay(bus, rails))
        bus.controls = controls
        lock.acquire()
        with self.assertRaises(RuntimeError): status(controls, 1, background=True)
        self.assertFalse(controls.lock.locked())
        lock.release()
        with patch.object(controls, '_check_idle', side_effect=RuntimeError('call active')):
            with self.assertRaises(RuntimeError): status(controls, 1, background=True)
        self.assertEqual(bus.sent, [])
        self.assertEqual(status(controls, 1, background=True)['state'], 'paused')
        self.assertFalse(lock.locked())

    def test_latest_only_and_no_stale_replay(self):
        publisher = MusicPublisher('wss://monitor.example/ws/gateways/pi-1', 'secret')
        publisher.publish(dict(railing_id=1, position=1))
        publisher.publish(dict(railing_id=1, position=2))
        self.assertEqual(publisher.drain(), [dict(railing_id=1, position=2)])
        with patch('music_sync.time.monotonic', return_value=0):
            publisher.publish(dict(railing_id=2))
        with patch('music_sync.time.monotonic', return_value=6):
            self.assertEqual(publisher.drain(), [])

    def test_authenticated_tls_url(self):
        for url in ['ws://192.168.0.2/ws/gateways/pi', 'wss:///ws/gateways/pi',
                    'wss://user:secret@host/ws/gateways/pi', 'wss://host/ws/gateways/pi?token=x',
                    'wss://host/ws/gateways/', 'wss://host/ws/gateways/pi/other']:
            with self.assertRaises(ValueError): validate_url(url)
        validate_url('ws://127.0.0.1/ws/gateways/pi')
        validate_url('wss://monitor.example/ws/gateways/pi')

    def test_round_robin_visits_one_rail_per_interval(self):
        sync = MusicSync(None, [1, 2, 3])
        visited = []
        sync.sample = visited.append
        with patch.object(sync.stop, 'wait', side_effect=[False, False, False, True]) as wait:
            sync._run()
        self.assertEqual(visited, [1, 2, 3])
        self.assertEqual([c.args for c in wait.call_args_list], [(2.0,)] * 4)

    def test_socket_uses_auth_and_never_claims_command_applied(self):
        import asyncio
        import json
        publisher = MusicPublisher('wss://monitor.example/ws/gateways/pi-1', 'secret')
        publisher.publish(dict(version=1, type='music_state', railing_id=1))
        sent = []
        class Socket:
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            async def send(self, raw): sent.append(json.loads(raw))
            async def recv(self):
                publisher.stop.set()
                return json.dumps(dict(type='command', message_id='request-1'))
        def connect(url, **kwargs):
            self.assertEqual(kwargs['additional_headers'], {'Authorization': 'Bearer secret'})
            return Socket()
        asyncio.run(publisher._run(connect))
        self.assertEqual(sent[0]['type'], 'music_state')
        self.assertEqual(sent[1], dict(version=1, type='ack', message_id='request-1', status='FAILED'))
