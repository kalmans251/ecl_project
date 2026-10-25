"""Bounded remote music/general commands with one durable no-replay journal."""
from datetime import datetime
import hashlib
import json
import logging
import re
from pathlib import Path
import sqlite3
import threading
import time
import uuid
from music_info import GROUPS, page, play, seek
from control_remote import OPERATIONS, parts as control_parts


LOG = logging.getLogger('cctv.remote')


class MusicRemote:
    def __init__(self, controls, rails, journal):
        self.controls, self.rails = controls, frozenset(rails)
        self.lock = threading.Lock()
        path = Path(journal).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = str(path)
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE IF NOT EXISTS requests (id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, expires REAL NOT NULL, result TEXT)')

    def handle(self, message, connected=lambda: True):
        ident = message.get('message_id')
        cctv = message.get('type') in ('cctv.enter', 'cctv.age')
        general = message.get('operation') in OPERATIONS and not cctv
        answer = dict(version=1, type='ack' if cctv else 'control_result' if general else 'music_result', message_id=ident, status='FAILED', data=None)
        if cctv:
            answer.pop('data')
        if not self.lock.acquire(blocking=False):
            return dict(version=1, type='ack', message_id=ident, status='BUSY')
        try:
            try:
                if str(uuid.UUID(ident)) != ident or message.get('version') != 1 or (not cctv and message.get('type') != 'command'):
                    raise ValueError('Invalid command')
                rail = message['railing_id']
                if type(rail) is not int or rail not in self.rails:
                    raise ValueError('Unconfigured railing')
                op = message['type'] if cctv else message['operation']
                value = message.get('value')
                if cctv:
                    camera = message.get('camera_id')
                    seq = message.get('event_seq')
                    if not isinstance(camera, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', camera):
                        raise ValueError('Invalid camera')
                    if type(seq) is not int or not 0 <= seq <= 0xffffffff:
                        raise ValueError('Invalid event sequence')
                    group = message.get('age_group')
                    if op == 'cctv.age' and group not in ('10','20','30','40','keep'):
                        raise ValueError('Invalid age group')
                    if op == 'cctv.enter' and group is not None:
                        raise ValueError('Unexpected age group')
                    observed = datetime.fromisoformat(message['observed_at'].replace('Z', '+00:00'))
                    expires = datetime.fromisoformat(message['expires_at'].replace('Z', '+00:00'))
                    if observed.tzinfo is None or expires.tzinfo is None or not 0 < (expires-observed).total_seconds() <= 5 or observed.timestamp() > time.time()+2:
                        raise ValueError('Invalid event time window')
                    command_parts = ['cctv', str(rail), op.split('.')[1], str(seq)]
                    if op == 'cctv.age': command_parts.append(group)
                    value = [camera, seq, group, message['observed_at']]
                elif general:
                    command_parts = control_parts(op, value, rail)
                elif not isinstance(value, str): raise ValueError('Invalid value')
                parts = value.split(':') if isinstance(value,str) else []
                if general or cctv: pass
                elif op == 'music.list':
                    if len(parts)!=2 or parts[0] not in GROUPS or parts[1] not in ('0','8','16','24'):
                        raise ValueError('Invalid page')
                elif op == 'music.play':
                    if len(parts)!=3 or parts[1] not in GROUPS or not parts[0].isascii() or not parts[0].isdecimal() or not 0 <= int(parts[0]) <= 0xffffffff or not parts[2].isascii() or not parts[2].isdecimal() or not 0 <= int(parts[2]) < 32:
                        raise ValueError('Invalid selection')
                elif op == 'music.seek':
                    if len(parts)!=2 or any(not p.isascii() or not p.isdecimal() for p in parts) or not 1<=int(parts[0])<=0xffffffff or not 0<=int(parts[1])<=0xffffffff:
                        raise ValueError('Invalid seek')
                else: raise ValueError('Unsupported operation')
                expiry = datetime.fromisoformat(message['expires_at'].replace('Z', '+00:00')).timestamp()
                ttl = expiry-time.time()
                if not 0 < ttl <= 46:
                    answer['status'] = 'EXPIRED'
                    return answer
                deadline = time.monotonic()+ttl
            except (ValueError, KeyError, TypeError, AttributeError):
                return answer
            fingerprint = hashlib.sha256(json.dumps([rail,op,value,message['expires_at']]).encode()).hexdigest()
            with sqlite3.connect(self.path) as db:
                previous = db.execute('SELECT fingerprint,result FROM requests WHERE id=?', (ident,)).fetchone()
                if previous:
                    if previous[0] != fingerprint: return answer
                    return json.loads(previous[1]) if previous[1] else dict(answer, status='FAILED' if cctv else 'UNKNOWN')
                db.execute('DELETE FROM requests WHERE expires<?', (time.time()-86400,))
                if db.execute('SELECT COUNT(*) FROM requests').fetchone()[0] >= 10000:
                    return answer
                # Commit before ANY PLC mutation: restart cannot replay an uncertain device action.
                db.execute('INSERT INTO requests VALUES(?,?,?,NULL)', (ident,fingerprint,expiry))
            def guard():
                if not connected() or time.monotonic() >= deadline:
                    raise TimeoutError('Connection/deadline ended; no further PLC sends')
            try:
                guard()
                if cctv:
                    LOG.info('CCTV event rail=%s type=%s seq=%s', rail, op, seq)
                    result = self.controls.execute(command_parts, guard=guard, structured=True)
                    answer['status'] = 'PLC_SENT' if result['device_application_confirmed'] else 'FAILED'
                elif general:
                    result = self.controls.execute(command_parts, guard=guard, structured=True)
                    result.update(operation=op,value=value)
                    answer.update(status='APPLIED' if result['device_application_confirmed'] else 'COMPLETED',data=result)
                elif op == 'music.list':
                    result = page(self.controls,rail,parts[0],int(parts[1]),guard=guard)
                    answer.update(status='COMPLETED',data=result)
                elif op == 'music.seek':
                    result=seek(self.controls,rail,int(parts[0]),int(parts[1]),guard=guard)
                    answer.update(status='APPLIED',data=result)
                else:
                    result = play(self.controls,rail,parts[1],parts[2],expected_version=int(parts[0]),guard=guard)
                    answer.update(status='APPLIED',data=result)
            except (ValueError, RuntimeError, OSError):
                answer['status'] = 'FAILED' if cctv else 'UNKNOWN'
            if cctv:
                LOG.info('CCTV event result rail=%s type=%s seq=%s status=%s', rail, op, seq, answer['status'])
            with sqlite3.connect(self.path) as db:
                db.execute('UPDATE requests SET result=? WHERE id=?', (json.dumps(answer),ident))
            return answer
        finally:
            self.lock.release()
