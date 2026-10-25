"""Latest-only visual metadata. Does not queue or modify railing control events."""
import logging
import math
import statistics
import threading
import time

MAX_TRACKS = 20
LOG = logging.getLogger('analytics.overlay')

def snapshot(rows, tracks, width, height, frame_id, age_state):
    people = []
    for tid, box in rows[:MAX_TRACKS]:
        x1, y1, x2, y2 = box
        if width <= 0 or height <= 0 or x2 <= x1 or y2 <= y1:
            continue
        state = tracks.get(tid, {})
        values = [v for v in state.get('ages', []) if math.isfinite(v) and 0 <= v <= 100]
        age = round(statistics.median(values), 1) if len(values) >= 2 else None
        label = 'estimated' if age is not None else age_state if age_state != 'ready' else 'unknown' if state.get('age_sent') else 'pending'
        people.append({'id': str(tid), 'box': [round(max(0, min(1, v)), 4) for v in (x1/width, y1/height, x2/width, y2/height)], 'age': age, 'state': label})
    return {'frame_id': str(frame_id), 'people': people}

class OverlayWorker(threading.Thread):
    def __init__(self, config, api):
        super().__init__(daemon=True)
        self.config, self.api = config, api
        self.latest = None
        self.warned = -10

    def run(self):
        import requests
        url = self.config['server_url'].rstrip('/') + '/api/cctv/analysis/' + self.config['camera_id'] + '/overlay'
        with requests.Session() as http:
            http.trust_env = False
            http.headers['Authorization'] = 'Bearer ' + self.config['analysis_token']
            while not self.api.stop.wait(.2):
                item = self.latest
                if not self.api.active() or item is None:
                    continue
                captured, payload = item
                age_ms = int((time.monotonic() - captured) * 1000)
                if not 0 <= age_ms <= 800:
                    continue
                try:
                    # No retry queue: a failed snapshot is replaced by the next frame.
                    response = http.post(url, json={**payload, 'age_ms': age_ms},
                                         timeout=.5, allow_redirects=False)
                    if not 200 <= response.status_code < 300 and time.monotonic() - self.warned > 10:
                        self.warned = time.monotonic()
                        LOG.warning('Overlay rejected status=%s; check server version and camera analysis permission', response.status_code)
                except requests.RequestException:
                    pass
