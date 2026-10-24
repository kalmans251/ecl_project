import base64
from datetime import datetime, timezone, timedelta
import tempfile
import unittest
import uuid
from audio import AudioManager
from railing import RailingManager
from voice import VoiceRelay
from voice.packet import VoicePacket
from protocol import AudioDirection, AudioEvent, Command, Codec2Mode
from music_remote import MusicRemote
from call_remote import CallRemote
from test_call_start import Bus, event

class WebCallTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.states=RailingManager();self.bus=Bus()
        self.audio=AudioManager(self.bus,self.states,ack_timeout=.001,attempts=1,recovery_grace_seconds=0)
        self.relay=VoiceRelay(self.bus,self.states)
        journal=self.temp.name+'/web.sqlite'
        MusicRemote(None,[1],journal)
        self.remote=CallRemote(self.audio,self.relay,self.states,[1],journal)
        self.cid=str(uuid.uuid4())
        def reply(frame):
            sid=self.states.snapshot(1)['call']['session_id']
            kind=AudioEvent.CALL_STARTED if frame.command==Command.START else AudioEvent.CALL_ENDED if frame.command==Command.STOP else AudioEvent.DIRECTION_CHANGED
            self.audio.handle_frame(event(session=sid,kind=kind,direction=frame.payload[0] if frame.command==Command.SET else AudioDirection.FIELD_TX,request=int.from_bytes(frame.payload[5:],'big') if frame.command==Command.SET else 0))
        self.bus.callback=reply
    def message(self,op):
        return dict(version=1,type='command',message_id=str(uuid.uuid4()),call_id=self.cid,railing_id=1,operation=op,expires_at=(datetime.now(timezone.utc)+timedelta(seconds=60)).isoformat())
    def test_lifecycle_duplicate_and_epoch(self):
        start=self.message('call.start');r=self.remote.handle(start);self.assertEqual('APPLIED',r['status']);count=len(self.bus.sent)
        self.assertEqual(r,self.remote.handle(start));self.assertEqual(count,len(self.bus.sent))
        sid=r['data']['session_id']
        packet=VoicePacket(1,int(AudioDirection.FIELD_TX),int(Codec2Mode.MODE_2400),0,8,6,bytes(range(48)),sid)
        self.remote.field(packet);self.assertEqual(base64.b64encode(packet.data).decode(),self.remote.drain()[0]['codec2'])
        on=self.message('ptt.on');self.assertEqual('APPLIED',self.remote.handle(on)['status'])
        sent=[];self.relay.forward_control_packet=lambda p,**kw: sent.append(p) or True
        message=dict(version=1,type='voice',call_id=self.cid,railing_id=1,direction='CONTROL_TX',epoch=on['message_id'],sequence=0,codec2=base64.b64encode(packet.data).decode())
        self.assertTrue(self.remote.receive(message));self.assertFalse(self.remote.receive(message));self.assertEqual(packet.data,sent[0].data)
        self.assertEqual('APPLIED',self.remote.handle(self.message('ptt.off'))['status'])
        self.assertEqual('APPLIED',self.remote.handle(self.message('ptt.on'))['status']);self.assertFalse(self.remote.receive(dict(message,sequence=1)))
        self.assertEqual('APPLIED',self.remote.handle(self.message('call.end'))['status']);self.assertIsNone(self.remote.current)
    def test_disconnect_blocks_audio_keepalive_and_can_hangup(self):
        self.remote.handle(self.message('call.start'));self.remote.disconnect()
        self.assertEqual('unknown',self.states.snapshot(1)['call']['phase'])
        count=len(self.bus.sent);self.audio.renew_calls();self.assertEqual(count,len(self.bus.sent))
        self.assertEqual('APPLIED',self.remote.handle(self.message('call.end'))['status'])
    def test_restart_mapping_allows_only_matching_hangup(self):
        self.remote.handle(self.message('call.start'));self.remote.disconnect()
        restored=CallRemote(self.audio,self.relay,self.states,[1],self.remote.path)
        wrong=self.message('call.end');wrong['call_id']=str(uuid.uuid4())
        self.assertEqual('FAILED',restored.handle(wrong)['status'])
        self.assertEqual('APPLIED',restored.handle(self.message('call.end'))['status'])
    def test_expired_or_disconnected_never_transmits(self):
        message=self.message('call.start');message['expires_at']='2000-01-01T00:00:00+00:00'
        self.assertEqual('EXPIRED',self.remote.handle(message)['status']);self.assertFalse(self.bus.sent)
        self.assertEqual('NOT_STARTED',self.remote.handle(self.message('call.start'),lambda:False)['status']);self.assertFalse(self.bus.sent)
    def test_uncertain_start_is_never_replayed(self):
        self.bus.callback=lambda f:None
        message=self.message('call.start');self.assertEqual('UNKNOWN',self.remote.handle(message)['status'])
        count=len(self.bus.sent);self.remote.handle(message);self.assertEqual(count,len(self.bus.sent))
    def test_end_after_pi_restart_restores_only_journaled_session(self):
        self.remote.handle(self.message('call.start'))
        # A cleared local call journal cannot silently claim a remote END.
        fresh=RailingManager();audio=AudioManager(self.bus,fresh,ack_timeout=.001,attempts=1,recovery_grace_seconds=0)
        relay=VoiceRelay(self.bus,fresh);remote=CallRemote(audio,relay,fresh,[1],self.remote.path)
        self.bus.callback=lambda f:audio.handle_frame(event(session=int.from_bytes(f.payload,'big'),kind=AudioEvent.CALL_ENDED))
        self.assertEqual('APPLIED',remote.handle(self.message('call.end'))['status'])
    def test_preflight_rejection_is_durable_and_never_replayed(self):
        self.states.reserve_call(1)
        message=self.message('call.start')
        result=self.remote.handle(message)
        self.assertEqual('NOT_STARTED',result['status'])
        self.assertEqual(self.cid,result['data']['call_id'])
        self.assertFalse(self.bus.sent)
        self.states.call_ended(1,session_id=self.states.snapshot(1)['call']['session_id'])
        self.assertEqual(result,self.remote.handle(message))
        self.assertFalse(self.bus.sent)

    def test_existing_binding_rejection_cannot_release_call(self):
        self.assertEqual('APPLIED',self.remote.handle(self.message('call.start'))['status'])
        self.assertEqual('FAILED',self.remote.handle(self.message('call.start'))['status'])
