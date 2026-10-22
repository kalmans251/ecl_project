"""Bounded remote music commands, with a durable no-replay journal."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3
import threading
import time
import uuid
from music_info import GROUPS, page, play


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
        answer = dict(version=1, type='music_result', message_id=ident, status='FAILED', data=None)
        if not self.lock.acquire(blocking=False):
            return dict(version=1, type='ack', message_id=ident, status='BUSY')
        try:
            try:
                if str(uuid.UUID(ident)) != ident or message.get('version') != 1 or message.get('type') != 'command':
                    raise ValueError('Invalid command')
                rail = message['railing_id']
                if type(rail) is not int or rail not in self.rails:
                    raise ValueError('Unconfigured railing')
                op = message['operation']
                value = message['value']
                if not isinstance(value, str): raise ValueError('Invalid value')
                parts = value.split(':')
                if op == 'music.list':
                    if len(parts)!=2 or parts[0] not in GROUPS or parts[1] not in ('0','8','16','24'):
                        raise ValueError('Invalid page')
                elif op == 'music.play':
                    if len(parts)!=3 or parts[1] not in GROUPS or not parts[0].isascii() or not parts[0].isdecimal() or not 0 <= int(parts[0]) <= 0xffffffff or not parts[2].isascii() or not parts[2].isdecimal() or not 0 <= int(parts[2]) < 32:
                        raise ValueError('Invalid selection')
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
                    return json.loads(previous[1]) if previous[1] else dict(answer, status='UNKNOWN')
                db.execute('DELETE FROM requests WHERE expires<?', (time.time()-86400,))
                if db.execute('SELECT COUNT(*) FROM requests').fetchone()[0] >= 10000:
                    return answer
                # Commit before ANY PLC mutation: restart cannot replay an uncertain play.
                db.execute('INSERT INTO requests VALUES(?,?,?,NULL)', (ident,fingerprint,expiry))
            def guard():
                if not connected() or time.monotonic() >= deadline:
                    raise TimeoutError('Connection/deadline ended; no further PLC sends')
            try:
                guard()
                if op == 'music.list':
                    result = page(self.controls,rail,parts[0],int(parts[1]),guard=guard)
                    answer.update(status='COMPLETED',data=result)
                else:
                    result = play(self.controls,rail,parts[1],parts[2],expected_version=int(parts[0]),guard=guard)
                    answer.update(status='APPLIED',data=result)
            except (ValueError, RuntimeError, OSError):
                answer['status'] = 'UNKNOWN'
            with sqlite3.connect(self.path) as db:
                db.execute('UPDATE requests SET result=? WHERE id=?', (json.dumps(answer),ident))
            return answer
        finally:
            self.lock.release()
