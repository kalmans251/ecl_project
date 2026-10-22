import json
import unittest
from device_control import DeviceControls
from protocol import Command, Frame, Node, Service
from railing import RailingManager
from voice import VoiceRelay

class Bus:
    def __init__(self):
        self.version = b'\x00\x00\x00\x05'
        self.bad_identity = False
        self.change = False
        self.sent = []
    def send_frame(self, f):
        self.sent.append(f)
        op = f.payload[4]
        if op == Command.MUSIC_CATALOG:
            data = self.version + b'\x00\x01' + bytes(8)
        elif op == Command.MUSIC_TRACK:
            identity = f.payload[5:12]
            if self.bad_identity: identity = bytes(7)
            data = identity + b'\x05a.mp3'
            if self.change: self.version = b'\x00\x00\x00\x06'
        else:
            data = b'\x02' + (12345).to_bytes(4, 'big') + b'\x05a.mp3'
        # Wrong source / token / rail must not complete the pending request.
        for src, token, rail in [(Node.P4, f.payload[:4], 1),
                                  (Node.WROOM, bytes(4), 1),
                                  (Node.WROOM, f.payload[:4], 2)]:
            self.controls.handle_frame(Frame(rail, src, Node.PI, Service.MUSIC,
                Command.APPLY_RESULT, token + bytes([op, 0]) + data))
            assert self.controls.result is None
        self.controls.handle_frame(Frame(f.railing_id, Node.WROOM, Node.PI, Service.MUSIC,
            Command.APPLY_RESULT, f.payload[:5] + b'\x00' + data))

class MusicInfoTests(unittest.TestCase):
    def setUp(self):
        self.bus = Bus()
        rails = RailingManager()
        self.controls = DeviceControls(self.bus, rails, VoiceRelay(self.bus, rails), ack_timeout=.01)
        self.bus.controls = self.controls
    def test_catalog_and_status(self):
        result = json.loads(self.controls.execute('music 1 list'.split()))
        self.assertEqual(result['tracks'], [{'group':'default', 'index':0, 'filename':'a.mp3'}])
        result = json.loads(self.controls.execute('music 1 status'.split()))
        self.assertEqual(result['state'], 'paused')
        self.assertEqual(result['position_ms'], 12345)
        self.assertIsNone(result['duration_ms'])
    def test_reject_wrong_identity(self):
        self.bus.bad_identity = True
        with self.assertRaises(ValueError): self.controls.execute('music 1 list'.split())
        self.assertIsNone(self.controls.pending)
    def test_reject_changed_catalog(self):
        self.bus.change = True
        with self.assertRaises(RuntimeError): self.controls.execute('music 1 list'.split())
    def test_validate_before_sending(self):
        for line in ('music 1 status 2', 'music 1 list 50', 'music 1 list default extra'):
            with self.assertRaises(ValueError): self.controls.execute(line.split())
        self.assertEqual(self.bus.sent, [])
