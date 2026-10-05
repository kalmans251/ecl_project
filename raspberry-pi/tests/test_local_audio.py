import ctypes.util
from array import array
from dataclasses import replace
import math
import threading
import time
import unittest
from unittest.mock import patch

from audio import AudioManager
from protocol import AudioDataType, AudioDirection, AudioEvent, CallOrigin, Command, Frame, Node, Service
from railing import RailingManager
from voice import VoiceRelay, VoicePacket
from voice.local_audio import LocalAudio


def wait_for(predicate):
    deadline = time.monotonic() + 2
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError('Worker did not reach expected state')
        time.sleep(0.005)


class Stream:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.running = self.closed = False
    def start(self): self.running = True
    def stop(self): self.running = False
    def close(self): self.closed = True


class SD:
    RawInputStream = RawOutputStream = Stream
    @staticmethod
    def check_input_settings(**kwargs): pass
    @staticmethod
    def check_output_settings(**kwargs): pass


class Status:
    input_overflow = output_underflow = False


class Bus:
    def __init__(self):
        self.sent = []
        self.callback = None
    def send_frame(self, frame): self.sent.append(frame)
    def send_control_frame(self, frame, **kwargs):
        self.sent.append(frame)
        if self.callback: self.callback(frame)


def event(kind, direction=0):
    return Frame(1, Node.P4, Node.PI, Service.AUDIO, Command.DATA,
                 bytes([AudioDataType.EVENT, kind, CallOrigin.EMERGENCY, direction]))


class LocalAudioTests(unittest.TestCase):
    def setUp(self):
        self.states = RailingManager()
        self.bus = Bus()
        self.relay = VoiceRelay(self.bus, self.states)
        self.states.call_started(1, CallOrigin.EMERGENCY, AudioDirection.CONTROL_TX)

    def test_transition_blocks_external_source_and_invalidates_local_token(self):
        packet = VoicePacket(1, AudioDirection.CONTROL_TX, 1, 0, 8, 6, bytes(48))
        token = self.relay.audio_token(1, AudioDirection.CONTROL_TX)
        self.assertTrue(self.relay.forward_control_packet(packet))
        with self.relay.control_transition():
            self.assertIsNone(self.relay.audio_token(1, AudioDirection.CONTROL_TX))
            self.assertFalse(self.relay.forward_control_packet(packet))
            self.assertFalse(self.relay.forward_control_packet(packet, token=token))
        self.assertFalse(self.relay.forward_control_packet(packet, token=token))
        self.assertTrue(self.relay.forward_control_packet(packet))
        with self.assertRaises(TimeoutError):
            with self.relay.control_transition():
                raise TimeoutError('P4 did not confirm')
        self.assertFalse(self.relay.forward_control_packet(packet))
        with self.relay.control_transition(): pass
        self.assertTrue(self.relay.forward_control_packet(packet))

    def test_transition_drains_inflight_write_before_command(self):
        entered, release, control = threading.Event(), threading.Event(), threading.Event()
        def slow_write(frame):
            entered.set()
            self.assertTrue(release.wait(2))
        self.bus.send_frame = slow_write
        packet = VoicePacket(1, AudioDirection.CONTROL_TX, 1, 0, 8, 6, bytes(48))
        sender = threading.Thread(target=self.relay.forward_control_packet, args=(packet,))
        sender.start()
        self.assertTrue(entered.wait(1))
        def transition():
            with self.relay.control_transition(): control.set()
        controller = threading.Thread(target=transition)
        controller.start()
        wait_for(lambda: self.relay._transitioning)
        self.assertFalse(control.is_set())
        release.set()
        sender.join(2); controller.join(2)
        self.assertFalse(sender.is_alive() or controller.is_alive())
        self.assertTrue(control.is_set())

    def test_hangup_requires_p4_confirmation(self):
        audio = AudioManager(self.bus, self.states, ack_timeout=0.01, attempts=2)
        with self.assertRaises(TimeoutError):
            audio.end_call(1)
        self.assertEqual(len(self.bus.sent), 2)
        self.bus.callback = lambda frame: audio.handle_frame(event(AudioEvent.CALL_ENDED))
        audio.end_call(1)
        self.assertIsNone(self.states.get_call_direction(1))

    @unittest.skipUnless(ctypes.util.find_library('codec2'), 'requires real Codec2')
    def test_usb_encode_aux_decode_ptt_and_cleanup(self):
        local = LocalAudio(self.relay, 1, '1', '0')
        self.addCleanup(local.close)
        local.start(SD)
        streams = list(local.streams)
        self.assertEqual(streams[0].kwargs['device'], 1)
        self.assertEqual(streams[1].kwargs['device'], 0)
        pcm = array('h', (int(10000 * math.sin(i * 2 * math.pi * 440 / 48000))
                         for i in range(960))).tobytes()
        for _ in range(8):
            local._capture_callback(pcm, 960, None, Status())
            time.sleep(0.005)
        wait_for(lambda: local.sent_packets == 1)
        source = VoicePacket.from_audio_payload(1, self.bus.sent[0].payload)
        self.assertEqual(len(source.data), 48)
        self.assertEqual(source.direction, AudioDirection.CONTROL_TX)
        # Local mode reserves the selected rail, so a forgotten TCP mic cannot mix in.
        self.assertFalse(self.relay.forward_control_packet(source))
        audio = AudioManager(self.bus, self.states, ack_timeout=0.05)
        def confirm(frame):
            self.assertIsNone(self.relay.audio_token(1, AudioDirection.CONTROL_TX))
            audio.handle_frame(event(AudioEvent.DIRECTION_CHANGED, frame.payload[0]))
            self.relay.state_changed()
        self.bus.callback = confirm
        with self.relay.control_transition():
            # Queued old mic frames must never become a later CONTROL packet.
            local._capture_callback(pcm, 960, None, Status())
            audio.set_direction(1, AudioDirection.FIELD_TX)
        count = len(self.bus.sent)
        for _ in range(8): local._capture_callback(pcm, 960, None, Status())
        time.sleep(0.06)
        self.assertEqual(len(self.bus.sent), count)
        for seq in range(4):
            packet = replace(source, direction=AudioDirection.FIELD_TX, sequence=seq)
            self.assertTrue(self.relay.handle_plc_frame(Frame(1, Node.S3, Node.PI,
                Service.AUDIO, Command.DATA, packet.to_audio_payload())))
            # Original compressed bytes remain available to the future monitoring client.
            self.assertEqual(self.relay._outbound.get_nowait(), packet.encode_network())
        wait_for(lambda: local.received_packets == 4)
        output = bytearray(1920)
        local._output_callback(output, 960, None, Status())
        self.assertTrue(any(output))
        with self.relay.control_transition():
            local._output_callback(output, 960, None, Status())
            self.assertFalse(any(output))
            audio.set_direction(1, AudioDirection.CONTROL_TX)
        for _ in range(8):
            local._capture_callback(pcm, 960, None, Status())
            time.sleep(0.005)
        wait_for(lambda: local.sent_packets == 2)
        self.assertIsNone(local.error)
        local.close()
        self.assertTrue(all(s.closed for s in streams))
        self.assertFalse(local.threads)
        self.assertIsNone(self.relay._field_handler)

    @unittest.skipUnless(ctypes.util.find_library('codec2'), 'requires real Codec2')
    def test_main_single_process_ptt_off_hangup(self):
        import main
        import io
        import sys
        from contextlib import redirect_stdout
        class ConsoleBus(Bus):
            closed = False
            def set_frame_handler(self, handler): self.handler = handler
            def open(self): self.handler(event(AudioEvent.CALL_STARTED, AudioDirection.FIELD_TX))
            def close(self): self.closed = True
            def send_control_frame(self, frame, **kwargs):
                self.sent.append(frame)
                if frame.command == Command.SET:
                    self.handler(event(AudioEvent.DIRECTION_CHANGED, frame.payload[0]))
                elif frame.command == Command.STOP:
                    self.handler(event(AudioEvent.CALL_ENDED))
        bus = ConsoleBus()
        argv = ['main.py', '--local-audio', '--mic-device', '1', '--speaker-device', '0',
                '--disable-voice-relay']
        with patch.object(sys, 'argv', argv), patch.dict(sys.modules, {'sounddevice': SD}), \
                patch('main.PlcBus', return_value=bus), \
                patch('builtins.input', side_effect=['led 1 basic', 'ptt 1 on', 'ptt 1 off', 'hangup 1',
                    'volume 1 101', 'volume 1 10', 'led 1 basic', 'query 1 wroom', 'quit']), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(main.main(), 0)
        self.assertEqual([f.command for f in bus.sent],
            [Command.SET, Command.SET, Command.STOP, Command.SET, Command.SET, Command.STATUS_REQUEST])
        self.assertEqual(bus.sent[3].payload, b'\x03\x0a')
        self.assertEqual(bus.sent[-1].dst, Node.WROOM)
        self.assertTrue(bus.closed)

    def test_start_failure_closes_partial_resources(self):
        class BrokenSD(SD):
            @staticmethod
            def RawOutputStream(**kwargs): raise RuntimeError('AUX unavailable')
        stream = Stream()
        with patch.object(BrokenSD, 'RawInputStream', return_value=stream), \
                patch('voice.local_audio.Codec2Encoder'), patch('voice.local_audio.Codec2Decoder'):
            local = LocalAudio(self.relay)
            with self.assertRaisesRegex(RuntimeError, 'AUX unavailable'):
                local.start(BrokenSD)
            self.assertTrue(stream.closed)
            self.assertIsNone(local.encoder)
            self.assertIsNone(local.decoder)
