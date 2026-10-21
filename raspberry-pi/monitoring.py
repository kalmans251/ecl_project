"""Optional, call-control-only gateway. Never executes CLI strings or replays a call."""
import json
import logging
import os
import queue
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID
from protocol import AudioDirection

LOG = logging.getLogger(__name__)
OPERATIONS = {'call.start', 'call.end', 'ptt.on', 'ptt.off'}


class CallGateway:
    def __init__(self, audio, railings, voice, url, token, state_file, rail_ids):
        parsed = urlparse(url)
        if (parsed.scheme != 'wss' and not (parsed.scheme == 'ws' and parsed.hostname in ('localhost', '127.0.0.1', '::1'))
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or not parsed.path.startswith('/ws/gateways/') or len(token) < 32):
            raise ValueError('Use WSS /ws/gateways/<id> and a dedicated gateway token (WS: loopback only)')
        self.audio, self.railings, self.voice = audio, railings, voice
        self.url, self.token, self.rail_ids = url, token, set(rail_ids)
        self.path = Path(state_file).expanduser()
        self.lock = threading.RLock()
        self.data = json.loads(self.path.read_text()) if self.path.exists() else {'binding': None, 'receipts': {}}
        if set(self.data) != {'binding', 'receipts'} or not isinstance(self.data['receipts'], dict):
            raise ValueError('Invalid monitoring journal')
        for receipt in self.data['receipts'].values():
            if receipt['status'] == 'RECEIVED' or (receipt['status']=='APPLIED' and receipt['message']['operation']!='call.end'): receipt['status'] = 'FAILED'
        self.jobs = queue.Queue(maxsize=1)
        self.stop = threading.Event()
        self.socket = None
        self.sequence = 0
        self.accepted_connections = {}
        self.threads = []
        self._save()

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(dir=self.path.parent, prefix=self.path.name+'.')
        try:
            with os.fdopen(fd, 'w') as out:
                json.dump(self.data, out); out.flush(); os.fsync(out.fileno())
            os.replace(name, self.path)
        finally:
            if os.path.exists(name): os.unlink(name)

    def _send(self, message):
        with self.lock:
            if self.socket: self.socket.send(json.dumps(message))

    def _ack(self, mid, status):
        self._send({'version': 1, 'type': 'ack', 'message_id': mid, 'status': status})

    def accept(self, message):
        if message.get('type') == 'welcome': return
        required = {'version','type','message_id','railing_id','operation','expires_at','call_id'}
        if (set(message) != required or message['version'] != 1 or message['type'] != 'command'
                or message['operation'] not in OPERATIONS or type(message['railing_id']) is not int
                or message['railing_id'] not in self.rail_ids):
            # Other gateway functions intentionally remain unsupported in this adapter.
            if message.get('type') == 'command' and isinstance(message.get('message_id'), str):
                self._ack(message['message_id'], 'FAILED')
            return
        mid, cid = str(UUID(message['message_id'])), str(UUID(message['call_id']))
        if mid != message['message_id'] or cid != message['call_id']: raise ValueError('Noncanonical UUID')
        expires = datetime.fromisoformat(message['expires_at'].replace('Z', '+00:00')).timestamp()
        if not time.time() < expires <= time.time()+30:
            self._ack(mid, 'EXPIRED'); return
        with self.lock:
            prior = self.data['receipts'].get(mid)
            if prior:
                if prior['message'] != message: raise ValueError('Reused command ID')
                self._ack(mid, prior['status']); return
            if not self.jobs.empty() or getattr(self, 'busy', False):
                self._ack(mid, 'BUSY'); return
            self.data['receipts'] = {k:v for k,v in self.data['receipts'].items() if v['expires'] > time.time()-60}
            self.data['receipts'][mid] = {'message': message, 'expires': expires, 'status': 'RECEIVED'}
            self._save()  # durable before acknowledging receipt or touching hardware
            self.accepted_connections[mid] = self.socket
            self.jobs.put_nowait(message)
            self._ack(mid, 'RECEIVED')

    def execute(self, message):
        mid, rid, cid, op = message['message_id'], message['railing_id'], message['call_id'], message['operation']
        status = 'FAILED'
        try:
            with self.lock:
                if not self.socket or self.stop.is_set() or self.socket is not self.accepted_connections.get(mid): raise RuntimeError('Gateway disconnected')
                if self.data['receipts'][mid]['expires'] <= time.time():
                    status = 'EXPIRED'; raise RuntimeError('Expired in queue')
                connection = self.socket
                binding = self.data['binding']
                call = self.railings.snapshot(rid).get('call', {})
                if op == 'call.start':
                    if any(self.railings.call_pending(r) for r in self.railings.snapshot()) or (binding and binding['call_id'] == cid):
                        raise RuntimeError('Unresolved or already used call; hangup first')
                    # Other-rail reservations are checked atomically by AudioManager.
                    self.data['binding'] = {'call_id': cid, 'railing_id': rid, 'session_id': 0, 'previous_session':call.get('session_id',0)}
                elif not binding or binding['call_id'] != cid or binding['railing_id'] != rid:
                    # Only explicit hangup may adopt a recovered/local call for cleanup.
                    if op != 'call.end' or not self.railings.call_pending(rid):
                        raise RuntimeError('No matching call')
                    self.data['binding'] = {'call_id': cid, 'railing_id': rid, 'session_id': call['session_id']}
                self._save()
            with self.voice.control_transition():
                if op == 'call.start': confirmed = self.audio.start_call(rid)
                elif op == 'call.end': confirmed = self.audio.end_call(rid)
                else:
                    self.audio.set_direction(rid, AudioDirection.CONTROL_TX if op == 'ptt.on' else AudioDirection.FIELD_TX)
                    confirmed = True
                if not confirmed: raise RuntimeError('No fresh device confirmation')
                with self.lock:
                    if self.socket is not connection:
                        call=self.railings.snapshot(rid).get('call', {})
                        self.railings.call_direction_unknown(rid,call.get('session_id',0),error='GATEWAY_OFFLINE')
                        raise RuntimeError('Connection changed during command')
            status = 'APPLIED'
        except Exception:
            LOG.warning('Monitoring call command failed operation=%s rail=%d; check call state', op, rid)
        finally:
            with self.lock:
                binding = self.data['binding']
                if binding and binding['call_id'] == cid:
                    call=self.railings.snapshot(rid).get('call', {})
                    if call.get('session_id',0) != binding.get('previous_session',-1):
                        binding['session_id'] = call.get('session_id', 0)
                        binding['ended'] = call.get('phase') == 'ended'
                self.accepted_connections.pop(mid, None)
                self.data['receipts'][mid]['status'] = status
                self._save()
                self.busy = False
            try: self._ack(mid, status)
            except Exception: pass  # saved outcome is available to a duplicate, never replayed
            self.voice.state_changed()

    def publish(self):
        with self.lock:
            binding = self.data['binding']
            if not binding: return
            call = self.railings.snapshot(binding['railing_id']).get('call', {})
            if not call and binding.get('ended'):
                call={'session_id':binding['session_id'],'phase':'ended'}
            sid = call.get('session_id', 0)
            phase = call.get('phase', 'unknown')
            if phase == 'idle' or (binding['session_id'] and binding['session_id'] != sid):
                return  # missing journal/local state never proves END
            if not sid or sid == binding.get('previous_session'): return
            if binding['session_id'] != sid:
                binding['session_id'] = sid; self._save()
            if phase=='ended' and not binding.get('ended'):
                binding['ended']=True;self._save()
            self.sequence += 1
            self._send({'version':1, 'type':'call_state', **{k:binding[k] for k in ('call_id','railing_id','session_id')}, 'sequence':self.sequence,
                        'phase':phase, 'direction':{1:'FIELD_TX',2:'CONTROL_TX'}.get(call.get('direction'),''),
                        'error':call.get('error','')})

    def disconnected(self):
        with self.lock:
            self.socket = None
            binding = self.data['binding']
            if binding:
                rid = binding['railing_id']
                call = self.railings.snapshot(rid).get('call', {})
                if self.railings.call_pending(rid):
                    self.railings.call_direction_unknown(rid, call.get('session_id',0), error='GATEWAY_OFFLINE')
                    self.voice.state_changed()  # stop keepalive/audio; P4 lease handles physical stop

    def _worker(self):
        while not self.stop.is_set():
            try: message = self.jobs.get(timeout=.2)
            except queue.Empty: continue
            with self.lock: self.busy = True
            try: self.execute(message)
            finally:
                with self.lock: self.busy = False

    def _network(self):
        import websocket
        while not self.stop.is_set():
            ws = None
            try:
                ws = websocket.create_connection(self.url, header={'Authorization':'Bearer '+self.token}, timeout=1, enable_multithread=True)
                with self.lock: self.socket = ws
                last = 0
                while not self.stop.is_set():
                    try:
                        raw = ws.recv()
                        if not raw: break
                        if not isinstance(raw,str) or len(raw.encode())>4096: raise ValueError('Oversize message')
                        self.accept(json.loads(raw))
                    except websocket.WebSocketTimeoutException: pass
                    if time.monotonic()-last >= 1:
                        self.publish(); last=time.monotonic()
            except Exception:
                LOG.warning('Monitoring connection unavailable; retrying')
            finally:
                self.disconnected()
                if ws: ws.close()
            self.stop.wait(3)

    def start(self):
        import websocket  # fail before launching threads if optional dependency is absent
        for target in (self._worker,self._network):
            thread=threading.Thread(target=target,daemon=True);thread.start();self.threads.append(thread)

    def close(self):
        self.stop.set()
        with self.lock: ws=self.socket
        if ws: ws.close()
        self.disconnected()
        for thread in self.threads: thread.join(timeout=2)
