"""WSS call ownership and bounded Codec2 bridge (no second PLC reader)."""
import base64
from datetime import datetime
import hashlib
import json
import logging
import queue
import secrets
import sqlite3
import threading
import time
import uuid
from protocol import AudioDirection, Codec2Mode
from voice.packet import VoicePacket

LOG = logging.getLogger('call.remote')

OPERATIONS = frozenset(('call.start', 'call.end', 'ptt.on', 'ptt.off'))

class CallRemote:
    def __init__(self, audio, relay, states, rails, journal):
        self.audio, self.relay, self.states = audio, relay, states
        self.rails, self.path = frozenset(rails), journal
        self.lock = threading.RLock()
        self.outbound = queue.Queue(maxsize=2)
        self.current = None
        self.sequence = None
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE IF NOT EXISTS web_calls (id TEXT PRIMARY KEY, rail INTEGER, session INTEGER, epoch TEXT, ended INTEGER DEFAULT 0)')

    def handle(self, message, connected=lambda: True):
        ident = message.get('message_id')
        result = dict(version=1, type='call_result', message_id=ident, status='FAILED', data=None)
        try:
            call_id, rail, op = message['call_id'], message['railing_id'], message['operation']
            if (str(uuid.UUID(ident)) != ident or str(uuid.UUID(call_id)) != call_id or
                message.get('version') != 1 or message.get('type') != 'command' or op not in OPERATIONS or
                type(rail) is not int or rail not in self.rails or message.get('value') is not None):
                return result
            recovery = message.get('recover', False)
            supplied_session = message.get('session_id')
            if (type(recovery) is not bool or
                (recovery and op != 'call.end') or
                (supplied_session is not None and (not recovery or
                 type(supplied_session) is not int or not 1 <= supplied_session <= 0xffffffff))):
                return result
            expiry = datetime.fromisoformat(message['expires_at'].replace('Z', '+00:00')).timestamp()
            ttl = expiry-time.time()
            if not 0 < ttl <= 65:
                return dict(result, status='EXPIRED')
        except (KeyError, TypeError, ValueError, AttributeError):
            return result
        LOG.info('Web call request rail=%s operation=%s call=%s', rail, op, call_id)
        deadline = time.monotonic()+ttl
        def guard():
            if not connected() or time.monotonic() >= deadline:
                raise TimeoutError('Web call connection/deadline expired')
        identity = [call_id, rail, op, message['expires_at']]
        if recovery: identity += [recovery, supplied_session]
        fingerprint = hashlib.sha256(json.dumps(identity).encode()).hexdigest()
        with sqlite3.connect(self.path) as db:
            old = db.execute('SELECT fingerprint,result FROM requests WHERE id=?', (ident,)).fetchone()
            if old:
                if old[0] != fingerprint: return result
                return json.loads(old[1]) if old[1] else dict(result, status='UNKNOWN')
            binding = db.execute('SELECT rail,session,epoch,ended FROM web_calls WHERE id=?', (call_id,)).fetchone()
            if op == 'call.start':
                if binding:
                    return result  # Existing call identity must never release a reservation.
                if (db.execute('SELECT COUNT(*) FROM web_calls').fetchone()[0]>=10000 or
                    any(s['call']['phase'] not in ('idle','ended') for s in self.states.snapshot().values())):
                    # Durable proof that this NEW web call never reached AudioManager/PLC.
                    rejected = dict(result, status='NOT_STARTED', data=dict(
                        call_id=call_id, railing_id=rail, epoch=ident))
                    db.execute('INSERT INTO requests VALUES(?,?,?,?)',
                               (ident,fingerprint,expiry,json.dumps(rejected)))
                    LOG.warning('Web call rejected before execution rail=%s; local call unresolved or journal full', rail)
                    return rejected
            elif not binding:
                if not recovery:
                    LOG.warning('Web call mapping missing rail=%s call=%s; server recovery required', rail, call_id)
                    return result
                # Do not adopt a different local/web owner merely because the server lost its journal.
                pending = [(int(r), v['call']) for r,v in self.states.snapshot().items()
                           if v['call']['phase'] not in ('idle','ended') or v['call']['active']]
                if (any(r != rail or c['session_id'] != supplied_session for r,c in pending) or
                    db.execute('SELECT 1 FROM web_calls WHERE ended=0 LIMIT 1').fetchone()):
                    LOG.warning('Web hangup recovery refused: another session owns the bus rail=%s', rail)
                    return result
                session = supplied_session or (secrets.randbelow(0xffffffff)+1)
                guard()
                if db.execute('SELECT COUNT(*) FROM web_calls').fetchone()[0]>=10000:
                    return result
                db.execute('INSERT INTO web_calls(id,rail,session,epoch) VALUES(?,?,?,?)',
                           (call_id,rail,session,ident))
                binding = (rail,session,ident,0)
                LOG.warning('Web hangup recovery rail=%s session=%s; waiting for physical END confirmation', rail, session)
            elif binding[0] != rail or (supplied_session is not None and binding[1] != supplied_session):
                LOG.warning('Web call session mismatch rail=%s call=%s', rail, call_id)
                return result
            db.execute('DELETE FROM requests WHERE expires<?', (time.time()-86400,))
            if db.execute('SELECT COUNT(*) FROM requests').fetchone()[0] >= 10000: return result
            db.execute('INSERT INTO requests VALUES(?,?,?,NULL)', (ident,fingerprint,expiry))
        try:
            guard()
            with self.lock:
                self.current = None
                self.sequence = None
                self._clear()
            with self.relay.control_transition():
                if op == 'call.start':
                    def reserved():
                        session = self.states.snapshot(rail)['call']['session_id']
                        with sqlite3.connect(self.path) as db:
                            db.execute('INSERT INTO web_calls(id,rail,session,epoch) VALUES(?,?,?,?)', (call_id,rail,session,ident))
                    if not self.audio.start_call(rail, guard=guard, reserved=reserved):
                        raise RuntimeError('Call not newly confirmed')
                    session = self.states.snapshot(rail)['call']['session_id']
                    direction = 'FIELD_TX'
                else:
                    _, session, _, ended = binding
                    call = self.states.snapshot(rail).get('call', {})
                    if not ended and (call.get('session_id') != session or
                                      (recovery and call.get('phase') in ('idle','ended'))):
                        if op!='call.end': raise RuntimeError('Different local call owns the rail')
                        self.states.recover_remote_call(rail,session)
                        call=self.states.snapshot(rail)['call']
                    if op == 'call.end':
                        if not ended and call.get('phase')!='ended' and not self.audio.end_call(rail, guard=guard):
                            raise RuntimeError('No remote end confirmation')
                        direction = 'IDLE'
                    else:
                        if ended: raise RuntimeError('Call already ended')
                        direction = 'CONTROL_TX' if op == 'ptt.on' else 'FIELD_TX'
                        self.audio.set_direction(rail, AudioDirection[direction], guard=guard)
                guard()
            with sqlite3.connect(self.path) as db:
                db.execute('UPDATE web_calls SET epoch=?,ended=? WHERE id=?', (ident,int(direction=='IDLE'),call_id))
            with self.lock:
                self.current = (call_id,rail,session,ident,direction) if direction!='IDLE' else None
            result.update(status='APPLIED', data=dict(call_id=call_id,railing_id=rail,session_id=session,direction=direction,epoch=ident))
        except (ValueError, RuntimeError, OSError, sqlite3.Error) as exc:
            LOG.warning('Web call failed rail=%s operation=%s: %s', rail, op, exc)
            result['status'] = 'UNKNOWN'
            if op == 'call.start':
                with sqlite3.connect(self.path) as db:
                    reserved = db.execute('SELECT 1 FROM web_calls WHERE id=?', (call_id,)).fetchone()
                # AudioManager invokes reserved() before any START transmission.
                if not reserved:
                    result.update(status='NOT_STARTED', data=dict(
                        call_id=call_id, railing_id=rail, epoch=ident))
            self.disconnect()
        with sqlite3.connect(self.path) as db:
            db.execute('UPDATE requests SET result=? WHERE id=?', (json.dumps(result),ident))
        return result

    def _clear(self):
        while True:
            try: self.outbound.get_nowait()
            except queue.Empty: return

    def disconnect(self):
        with self.lock:
            self.current = None
            self.sequence = None
            self._clear()
        # Stop renewing web-owned calls; retain session ownership for explicit hangup.
        with sqlite3.connect(self.path) as db:
            rows = db.execute('SELECT rail,session FROM web_calls WHERE ended=0').fetchall()
        for rail,session in rows:
            self.states.call_direction_unknown(rail,session)
        self.relay.state_changed()

    def field(self, packet):
        with self.lock:
            current = self.current
            if not current: return
            call_id,rail,session,epoch,direction = current
            if (direction!='FIELD_TX' or packet.railing_id!=rail or packet.session_id!=session or
                packet.frame_count!=8 or len(packet.data)!=48): return
            message = dict(version=1,type='voice',call_id=call_id,railing_id=rail,direction=direction,
                           epoch=epoch,sequence=packet.sequence,codec2=base64.b64encode(packet.data).decode())
            try: self.outbound.put_nowait((time.monotonic(),current,message))
            except queue.Full: pass

    def drain(self):
        result=[]
        with self.lock:
            while True:
                try: at,current,message=self.outbound.get_nowait()
                except queue.Empty: break
                if current==self.current and time.monotonic()-at<.4: result.append(message)
        return result

    def receive(self, message):
        with self.lock:
            current=self.current
            if not current: return False
            call_id,rail,session,epoch,direction=current
            if (message.get('version')!=1 or message.get('type')!='voice' or message.get('call_id')!=call_id or
                type(message.get('railing_id')) is not int or message['railing_id']!=rail or
                direction!='CONTROL_TX' or message.get('direction')!=direction or message.get('epoch')!=epoch):return False
            seq=message.get('sequence')
            if type(seq) is not int or not 0<=seq<=65535:return False
            if self.sequence is not None and not 0<((seq-self.sequence)&65535)<32768:return False
            try: data=base64.b64decode(message['codec2'],validate=True)
            except (KeyError, ValueError, TypeError):return False
            if len(data)!=48:return False
            self.sequence=seq
            token=self.relay.audio_token(rail,AudioDirection.CONTROL_TX)
        if token is None:return False
        return self.relay.forward_control_packet(VoicePacket(rail,int(AudioDirection.CONTROL_TX),
            int(Codec2Mode.MODE_2400),seq,8,6,data,session),token=token)
