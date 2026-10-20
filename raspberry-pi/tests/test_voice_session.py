import unittest
from dataclasses import replace
from protocol import AudioDirection, Command, Frame, Node, Service
from railing import RailingManager
from voice import VoicePacket, VoiceStreamParser
from test_voice_relay import CaptureRelay, FakeBus

class VoiceSessionTests(unittest.TestCase):
    def setUp(self):
        self.states=RailingManager();self.states.reserve_call(1)
        self.sid=self.states.snapshot(1)['call']['session_id']
        self.states.call_started(1,0,AudioDirection.CONTROL_TX)
        self.bus=FakeBus();self.relay=CaptureRelay(self.bus,self.states)
        self.packet=VoicePacket(1,2,1,7,8,6,bytes(range(48)),self.sid)

    def test_wire_roundtrip_keeps_id_and_rejects_old_layout(self):
        p=self.packet
        self.assertEqual(len(p.to_audio_payload()),59)
        self.assertEqual(p.to_audio_payload()[7:11],self.sid.to_bytes(4,'big'))
        self.assertEqual(VoicePacket.from_audio_payload(1,p.to_audio_payload()),p)
        self.assertEqual(VoicePacket.decode_network(p.encode_network()),p)
        with self.assertRaises(ValueError):VoicePacket.from_audio_payload(1,p.to_audio_payload()[:7]+p.data)
        old=bytearray(p.encode_network());old[2]=1
        self.assertEqual(VoiceStreamParser().feed(bytes(old)),[])

    def test_buffered_old_control_and_token_rejected_after_new_call(self):
        token=self.relay.audio_token(1,AudioDirection.CONTROL_TX)
        self.assertTrue(self.relay.forward_control_packet(self.packet,token=token))
        self.states.call_ended(1);self.states.reserve_call(1)
        self.states.call_started(1,0,AudioDirection.CONTROL_TX)
        self.assertFalse(self.relay.forward_control_packet(self.packet))
        sid=self.states.snapshot(1)['call']['session_id']
        fresh=replace(self.packet,session_id=sid)
        self.assertFalse(self.relay.forward_control_packet(fresh,token=token))
        self.assertTrue(self.relay.forward_control_packet(fresh))

    def test_old_field_packet_is_neither_played_nor_broadcast(self):
        self.states.call_direction_changed(1,AudioDirection.FIELD_TX)
        sink=[];self.relay.set_field_handler(sink.append)
        p=replace(self.packet,direction=1,session_id=self.sid^1)
        self.relay.handle_plc_frame(Frame(1,Node.S3,Node.PI,Service.AUDIO,Command.DATA,p.to_audio_payload()))
        self.assertEqual(sink,[]);self.assertEqual(self.relay.broadcasts,[])
        p=replace(p,session_id=self.sid)
        self.relay.handle_plc_frame(Frame(1,Node.S3,Node.PI,Service.AUDIO,Command.DATA,p.to_audio_payload()))
        self.assertEqual(sink,[p])
