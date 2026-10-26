"""Persist observed alarm transitions until the server acknowledges their exact ID."""
import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from datetime import datetime, timezone

class EmergencyOutbox:
    def __init__(self, path):
        path=Path(path).expanduser();path.parent.mkdir(parents=True,exist_ok=True)
        self.path=str(path);self.lock=threading.Lock();self.last=float('-inf')
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE IF NOT EXISTS alarm_identity(rail INTEGER PRIMARY KEY, identity TEXT, at INTEGER)')
            db.execute('CREATE TABLE IF NOT EXISTS alarm_outbox(n INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE, rail INTEGER, message TEXT)')
    def record(self, rail, identity):
        identity=json.dumps(identity)
        with self.lock, sqlite3.connect(self.path) as db:
            old=db.execute('SELECT identity,at FROM alarm_identity WHERE rail=?',(rail,)).fetchone()
            if old and old[0]==identity:return
            if old is None and not json.loads(identity)[0]:return
            at=max(int(time.time()*1000),old[1]+1 if old else 0)
            ident=str(uuid.uuid4())
            msg=dict(version=2,type='emergency_state',event_id=ident,railing_id=rail,
                observed_at=datetime.fromtimestamp(at/1000,timezone.utc).isoformat(),state=dict(active=json.loads(identity)[0]))
            db.execute('INSERT INTO alarm_outbox(id,rail,message) VALUES(?,?,?)',(ident,rail,json.dumps(msg)))
            db.execute('INSERT OR REPLACE INTO alarm_identity VALUES(?,?,?)',(rail,identity,at))
    def drain(self):
        with self.lock, sqlite3.connect(self.path) as db:
            if time.monotonic()-self.last<1:return []
            self.last=time.monotonic()
            # One in flight per rail: START is acknowledged before its END.
            rows=db.execute('SELECT message FROM alarm_outbox WHERE n IN (SELECT MIN(n) FROM alarm_outbox GROUP BY rail) ORDER BY n LIMIT 255').fetchall()
            return [json.loads(r[0]) for r in rows]
    def acknowledge(self, msg):
        if (set(msg)!={'version','type','event_id','railing_id'} or type(msg['version']) is not int or msg['version']!=2 or
            msg['type']!='emergency_ack' or type(msg['railing_id']) is not int or not isinstance(msg['event_id'],str)):return
        with self.lock, sqlite3.connect(self.path) as db:
            db.execute('DELETE FROM alarm_outbox WHERE id=? AND rail=?',(msg['event_id'],msg['railing_id']))
