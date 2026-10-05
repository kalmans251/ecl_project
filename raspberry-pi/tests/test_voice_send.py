from array import array
import ctypes.util
from pathlib import Path
import socket
import subprocess
import sys
import threading
import unittest
from voice import VoiceStreamParser
from voice.playback import Codec2Decoder, Codec2Encoder
from tools.voice_send import downsample

class SendTests(unittest.TestCase):
    def test_capture_conversion(self):
        self.assertEqual(downsample(array('h',[1234]*960).tobytes(),48000), array('h',[1234]*160).tobytes())
        with self.assertRaises(ValueError): downsample(b'bad',48000)

    @unittest.skipUnless(ctypes.util.find_library('codec2'), 'requires libcodec2')
    def test_tone_client_over_real_tcp(self):
        received=bytearray()
        server=socket.socket()
        server.bind(('127.0.0.1',0)); server.listen(); server.settimeout(3)
        errors=[]
        def read():
            try:
                with server.accept()[0] as sock:
                    sock.settimeout(3)
                    while True:
                        data=sock.recv(4096)
                        if not data: break
                        received.extend(data)
            except Exception as exc: errors.append(exc)
        thread=threading.Thread(target=read); thread.start()
        try:
            script=Path(__file__).resolve().parents[1]/'tools'/'voice_send.py'
            result=subprocess.run([sys.executable,str(script),'--tone','--seconds','0.34','--port',str(server.getsockname()[1])],capture_output=True,text=True,timeout=5)
            self.assertEqual(result.returncode,0,result.stderr)
            thread.join(4)
            self.assertFalse(thread.is_alive())
            self.assertEqual(errors,[])
            packets=VoiceStreamParser().feed(bytes(received))
            self.assertEqual(len(packets),2)
            self.assertEqual([p.sequence for p in packets],[0,1])
            decoder=Codec2Decoder()
            try:
                for packet in packets:
                    self.assertEqual(packet.frame_count,8)
                    self.assertEqual(packet.direction,2)
                    self.assertEqual(len(decoder.decode(packet.data)),2560)
            finally: decoder.close()
        finally: server.close()

    @unittest.skipUnless(ctypes.util.find_library('codec2'), 'requires libcodec2')
    def test_encoder_size_and_close(self):
        encoder=Codec2Encoder()
        try:
            self.assertEqual(len(encoder.encode(bytes(320))),6)
            with self.assertRaises(ValueError): encoder.encode(bytes(319))
            encoder.close()
            with self.assertRaises(RuntimeError): encoder.encode(bytes(320))
        finally: encoder.close()
