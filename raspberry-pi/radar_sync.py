"""Demand-driven selected-sensor snapshots. All PLC exchanges are Pi initiated."""
from contextlib import ExitStack
from datetime import datetime, timezone
import logging
import secrets
import threading
import time
from protocol import Frame, Node, Service, Command

LOG = logging.getLogger('radar.sync')


def decode(payload, detail):
    if len(payload) < 15 or payload[4] != 1 or payload[5] not in (0, 1, 2):
        raise ValueError('Invalid radar schema/source')
    source, valid, count = payload[5:8]
    if valid not in (0, 1) or count > 3 or payload[14] != int(detail):
        raise ValueError('Invalid radar status')
    age = int.from_bytes(payload[12:14], 'big')
    if valid and (source == 0 or age > 1500):
        raise ValueError('Expired radar sample')
    if not valid and count:
        raise ValueError('Invalid sensor cannot claim people')
    if len(payload) != 15 + (count * 4 if detail and valid else 0):
        raise ValueError('Invalid radar payload length')
    points = []
    for offset in range(15, len(payload), 4):
        x = int.from_bytes(payload[offset:offset+2], 'big', signed=True)
        y = int.from_bytes(payload[offset+2:offset+4], 'big', signed=True)
        if not -10000 <= x <= 10000 or not 0 <= y <= 10000:
            raise ValueError('Invalid radar position')
        points.append(dict(x=x/1000, y=y/1000))
    return dict(source=source, available=bool(valid), count=count,
                sequence=int.from_bytes(payload[8:12], 'big'), age_ms=age,
                detail=bool(detail), targets=points)


class RadarSync:
    def __init__(self, bus, controls, audio, railings, ids, publish):
        self.bus, self.controls, self.audio, self.railings = bus, controls, audio, railings
        self.ids, self.publish = set(ids), publish
        self.stop = threading.Event()
        self.condition = threading.Condition()
        self.wanted = {}
        self.active = {}
        self.due = {}
        self.pending = self.result = None
        self.token = secrets.randbits(32)
        self.thread = None

    def demand(self, message):
        ids = message.get('rails')
        if message.get('version') != 1 or not isinstance(ids, list) or len(ids)>255:
            raise ValueError('Invalid radar demand')
        if any(type(r) is not int or r not in self.ids for r in ids):
            # Server may know rails not installed in this gateway process.
            ids = [r for r in ids if type(r) is int and r in self.ids]
        with self.condition:
            self.wanted = {r: time.monotonic()+6 for r in ids}
            self.active = {r:v for r,v in self.active.items() if r in self.wanted}
            self.due = {r:v for r,v in self.due.items() if r in self.wanted}

    def disconnect(self):
        with self.condition:
            self.wanted.clear(); self.active.clear(); self.due.clear()

    def start(self):
        self.thread = threading.Thread(target=self._run, name='radar-poll', daemon=True)
        self.thread.start()

    def close(self):
        self.stop.set()
        if self.thread: self.thread.join(2)

    def emit(self, rail, state):
        self.publish(dict(version=1, type='radar_state', railing_id=rail,
                          observed_at=datetime.now(timezone.utc).isoformat(), state=state))

    def handle_frame(self, frame):
        if (frame.src != Node.P4 or frame.dst != Node.PI or frame.service != Service.RADAR
                or frame.command != Command.STATUS_RESPONSE):
            return False
        with self.condition:
            if not self.pending or (frame.railing_id, frame.payload[:4]) != self.pending[:2]:
                return True
            try: result = decode(frame.payload, self.pending[2])
            except ValueError: return True
            self.result = result
            self.condition.notify_all()
        return True

    def query(self, rail, detail):
        with ExitStack() as stack:
            # Background work never waits for control ownership; same bus transaction lock.
            for lock in (self.controls.lock, self.audio._control_lock, self.bus.transaction()):
                if not lock.acquire(False): return None
                stack.callback(lock.release)
            if self.audio._keepalive_due.is_set(): return None
            states = self.railings.snapshot().values()
            if any(s['call']['active'] or s['call']['phase'] not in ('idle','ended')
                   or s['emergency']['active'] for s in states):
                return dict(available=False, reason='call_or_emergency')
            with self.condition:
                if self.wanted.get(rail, 0) <= time.monotonic(): return None
                self.token = (self.token+1) & 0xffffffff
                token = self.token.to_bytes(4, 'big')
                self.pending, self.result = (rail, token, detail), None
            try:
                self.bus.send_frame(Frame(rail, Node.PI, Node.P4, Service.RADAR,
                                          Command.STATUS_REQUEST, token+bytes([detail])))
                deadline = time.monotonic()+.6
                with self.condition:
                    while self.result is None and not self.stop.is_set():
                        remaining = deadline-time.monotonic()
                        if remaining <= 0: break
                        self.condition.wait(remaining)
                    return self.result or dict(available=False, reason='timeout')
            finally:
                with self.condition: self.pending = None

    def _run(self):
        while not self.stop.wait(.05):
            now = time.monotonic()
            with self.condition:
                candidates = [r for r,until in self.wanted.items()
                              if until>now and self.due.get(r,0)<=now]
                if not candidates: continue
                rail = min(candidates, key=lambda r:self.due.get(r,0))
                detail = self.active.get(rail,False)
            try: state = self.query(rail, detail)
            except (OSError, RuntimeError): state = dict(available=False, reason='transport')
            if state is None: continue
            with self.condition:
                if self.wanted.get(rail,0)<=time.monotonic(): continue
                active = state.get('available',False) and state.get('count',0)>0
                self.active[rail] = active
                # Presence first; fetch coordinates immediately after a positive presence reply.
                delay = 0 if active and not detail else (.5 if active else 2.0)
                self.due[rail] = time.monotonic()+delay
            self.emit(rail,state)
            # Global budget/fairness across rails; no burst of stale queued polls.
            self.stop.wait(.2)
