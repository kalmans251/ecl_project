"""Camera-local event identities; no model/GPU dependencies in policy tests."""
import time
import uuid
from datetime import datetime, timezone

def timestamp():
    return datetime.now(timezone.utc).isoformat()

class Entries:
    def __init__(self, camera, clock=time.monotonic, age_window=4.0, min_samples=3):
        self.camera, self.clock = camera, clock
        self.age_window = age_window
        self.min_samples = min_samples
        self.tracks = {}

    def update(self, ids):
        now = self.clock()
        self.tracks = {k: v for k, v in self.tracks.items() if now - v['seen'] < 3}
        events = []
        for tid in set(ids):
            state = self.tracks.setdefault(tid, {'seen': now, 'hits': 0, 'event': None, 'ages': [], 'age_sent': False, 'attempted': 0})
            if now - state['seen'] > .75:
                state['hits'] = 0
            state['seen'], state['hits'] = now, state['hits'] + 1
            if state['hits'] >= 3 and state['event'] is None:
                state['event'] = {'camera_id': self.camera, 'event_id': str(uuid.uuid4()), 'type': 'enter', 'observed_at': timestamp()}
                state['entered'] = now
                events.append(state['event'])
        return events

    def age(self, tid, event_id, value):
        state = self.tracks.get(tid)
        if not state or not state['event'] or state['event']['event_id'] != event_id or self.clock() - state['seen'] > .75:
            return
        if value is not None and 0 <= value <= 100:
            state['ages'].append(float(value))

    def age_events(self):
        import statistics
        events = []
        for state in self.tracks.values():
            if not state['event'] or state['age_sent']:
                continue
            age = self.clock() - state['entered']
            if age < self.age_window and not (age >= 2 and len(state['ages']) >= 5):
                continue
            group = 'keep'
            if len(state['ages']) >= self.min_samples:
                value = int(statistics.median(state['ages']) // 10) * 10
                if value in (10, 20, 30, 40):
                    group = str(value)
            state['age_sent'] = True
            events.append({**state['event'], 'type': 'age', 'age_group': group})
        return events
