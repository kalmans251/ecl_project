import unittest
from device_control import DeviceControls, device_status
from protocol import AudioDirection, CallOrigin, Command, Frame, Node, Service
from railing import RailingManager
from voice import VoiceRelay

class Bus:
    def __init__(self): self.sent = []
    def send_frame(self, frame): self.sent.append(frame)

class ControlsTests(unittest.TestCase):
    def setUp(self):
        self.bus = Bus()
        self.states = RailingManager()
        self.voice = VoiceRelay(self.bus, self.states)
        self.controls = DeviceControls(self.bus, self.states, self.voice)

    def test_exact_wire_contracts(self):
        cases = [
            ('projector 1 on', Service.PROJECTOR, Command.START, b'', Node.P4),
            ('projector 1 off', Service.PROJECTOR, Command.STOP, b'', Node.P4),
            ('led 1 on', Service.LED, Command.START, b'', Node.P4),
            ('led 1 off', Service.LED, Command.STOP, b'', Node.P4),
            ('led 1 basic', Service.LED, Command.SET, b'\x01', Node.P4),
            ('led 1 music', Service.LED, Command.SET, b'\x03', Node.P4),
            ('led 1 weather clear', Service.LED, Command.SET, b'\x02\x00', Node.P4),
            ('led 1 weather cloudy', Service.LED, Command.SET, b'\x02\x01', Node.P4),
            ('led 1 weather rain', Service.LED, Command.SET, b'\x02\x02', Node.P4),
            ('led 1 weather snow', Service.LED, Command.SET, b'\x02\x03', Node.P4),
            ('music 1 start', Service.MUSIC, Command.START, b'', Node.P4),
            ('music 1 stop', Service.MUSIC, Command.STOP, b'', Node.P4),
            ('music 1 pause', Service.MUSIC, Command.PAUSE, b'', Node.P4),
            ('music 1 resume', Service.MUSIC, Command.RESUME, b'', Node.P4),
            ('music 1 next', Service.MUSIC, Command.NEXT, b'', Node.P4),
            ('music 1 mode sequential', Service.MUSIC, Command.SET, b'\x01\x01', Node.P4),
            ('music 1 mode shuffle', Service.MUSIC, Command.SET, b'\x01\x02', Node.P4),
            ('music 1 mode age', Service.MUSIC, Command.SET, b'\x01\x03', Node.P4),
            ('volume 1 0', Service.MUSIC, Command.SET, b'\x03\x00', Node.P4),
            ('volume 1 100', Service.MUSIC, Command.SET, b'\x03\x64', Node.P4),
            ('sleep 1 on', Service.SLEEP, Command.START, b'', Node.P4),
            ('sleep 1 off', Service.SLEEP, Command.STOP, b'', Node.P4),
            ('detection 1 radar', Service.DETECTION, Command.SET, b'\x00', Node.P4),
            ('detection 1 cctv', Service.DETECTION, Command.SET, b'\x01', Node.P4),
            ('query 1 p4', Service.SYSTEM, Command.STATUS_REQUEST, b'', Node.P4),
            ('query 1 wroom', Service.SYSTEM, Command.STATUS_REQUEST, b'', Node.WROOM),
            ('query 1 s3', Service.SYSTEM, Command.STATUS_REQUEST, b'', Node.S3),
            ('ping 1', Service.SYSTEM, Command.PING, b'', Node.P4),
            ('power 1 on', Service.POWER, Command.START, b'', Node.P4),
            ('power 1 off', Service.POWER, Command.STOP, b'', Node.P4),
        ]
        for command, service, op, payload, destination in cases:
            with self.subTest(command=command):
                self.bus.sent.clear()
                result = self.controls.execute(command.split())
                self.assertIn('not confirmed', result)
                self.assertEqual(self.bus.sent, [Frame(1, Node.PI, destination, service, op, payload)])
                # Must be accepted by the existing parser including the CRC.
                from protocol import FrameParser
                self.assertEqual(FrameParser().feed(self.bus.sent[0].encode()), self.bus.sent)

    def test_power_selection_precedes_start(self):
        for mode, value in [('ac', 1), ('battery', 2)]:
            self.bus.sent.clear()
            self.controls.execute(['power', '0xff', mode])
            self.assertEqual([(f.railing_id, f.command, f.payload) for f in self.bus.sent],
                [(255, Command.SET, bytes([value])), (255, Command.START, b'')])

    def test_invalid_input_never_writes_uart(self):
        for line in ['volume 1 -1', 'volume 1 101', 'volume 1 x', 'volume 1 10 extra',
                     'led 1 weather fog', 'led 1 weather', 'led 1 basic extra',
                     'music 1 mode x', 'music 1 previous', 'music 1',
                     'power 1 auto', 'sleep 1 yes', 'projector 1 yes', 'query 1 all',
                     'ping 1 extra', 'ping 0', 'sleep 256 on', 'volume x 10']:
            with self.subTest(line=line), self.assertRaises(ValueError):
                self.controls.execute(line.split())
        self.assertEqual(self.bus.sent, [])
        self.assertIsNone(self.controls.execute(['unrelated']))

    def test_any_active_call_emergency_or_unresolved_ptt_blocks_controls(self):
        self.states.call_started(2, CallOrigin.NORMAL, AudioDirection.FIELD_TX)
        with self.assertRaisesRegex(RuntimeError, 'call/emergency'):
            self.controls.execute(['led', '1', 'basic'])
        self.states.call_ended(2)
        self.states.emergency_start(2, 1, 1)
        with self.assertRaises(RuntimeError): self.controls.execute(['query', '1', 'p4'])
        self.states.emergency_stop(2, 1)
        with self.assertRaises(TimeoutError):
            with self.voice.control_transition(): raise TimeoutError()
        with self.assertRaisesRegex(RuntimeError, 'unresolved'):
            self.controls.execute(['volume', '1', '20'])
        self.assertEqual(self.bus.sent, [])
        with self.voice.control_transition(): pass
        self.controls.execute(['volume', '1', '20'])
        self.assertEqual(len(self.bus.sent), 1)

    def test_new_call_blocks_remaining_power_frame(self):
        def send(frame):
            self.bus.sent.append(frame)
            self.states.call_started(1, CallOrigin.NORMAL, AudioDirection.FIELD_TX)
        self.bus.send_frame = send
        with self.assertRaises(RuntimeError): self.controls.execute(['power', '1', 'ac'])
        self.assertEqual(len(self.bus.sent), 1)
        self.assertEqual(self.bus.sent[0].command, Command.SET)

    def test_status_response_does_not_claim_full_p4_state(self):
        message = device_status(Frame(1, Node.P4, Node.PI, Service.SYSTEM,
                                     Command.STATUS_RESPONSE, b'\x01'))
        self.assertIn('alive=1', message)
        message = device_status(Frame(1, Node.WROOM, Node.PI, Service.SYSTEM,
                                     Command.STATUS_RESPONSE, b'\x01\x01\x02\x01'))
        self.assertIn('sd_mounted=1 music=paused', message)
        self.assertIsNone(device_status(Frame(1, Node.P4, Node.PI, Service.SYSTEM, Command.PONG)))
