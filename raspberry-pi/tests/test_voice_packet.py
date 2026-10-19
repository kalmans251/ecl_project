import unittest
from voice.packet import VoicePacket, VoicePacketError

class VoicePacketTests(unittest.TestCase):
    def test_round_trip(self):
        original = VoicePacket(65535, bytes(range(48)))
        self.assertEqual(VoicePacket.decode(original.encode()), original)

    def test_bad_length(self):
        with self.assertRaises(VoicePacketError):
            VoicePacket.decode(bytes([2,1,0,0,8,6,1]))
