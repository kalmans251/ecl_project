"""Latest-only CCTV occupancy renewal; never journal or count a new person."""
from datetime import datetime, timezone
import threading
import time
from music_info import request
from protocol import Command, Service, Node

class PresenceUpdates:
    def __init__(self, controls, rails):
        self.controls,self.rails=controls,frozenset(rails)
        self.lock=threading.Lock()
        self.pending={}

    def offer(self, message):
        try:
            rail=message['railing_id']
            observed=datetime.fromisoformat(message['observed_at'].replace('Z','+00:00'))
            expires=datetime.fromisoformat(message['expires_at'].replace('Z','+00:00'))
            now=datetime.now(timezone.utc)
            if (message.get('version')!=1 or message.get('type')!='cctv.presence'
                    or type(rail) is not int or rail not in self.rails
                    or observed.tzinfo is None or expires.tzinfo is None
                    or not 0<(expires-observed).total_seconds()<=3
                    or observed.timestamp()>now.timestamp()+2 or expires<=now):
                return
            deadline=time.monotonic()+min(3,(expires-now).total_seconds())
        except (KeyError,TypeError,ValueError,AttributeError):
            return
        with self.lock:self.pending[rail]=deadline

    def step(self, connected):
        with self.lock:
            if not self.pending:return
            rail=next(iter(self.pending));deadline=self.pending.pop(rail)
        def guard():
            if not connected() or time.monotonic()>=deadline:
                raise RuntimeError('Presence expired or disconnected')
        try:
            guard()
            request(self.controls,rail,Command.DATA,bytes([4]),background=True,
                    timeout=.6,service=Service.DETECTION,expected=Node.P4,guard=guard)
        except (RuntimeError,ValueError,OSError):
            pass  # A later fresh observation may renew; never replay an old one.
