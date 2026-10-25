"""One camera per worker, server-side YOLO/ByteTrack + optional MiVOLO.
Video is read from local MediaMTX; only bounded events cross the Spring API.
"""
import argparse
import json
import logging
import multiprocessing as mp
import os
from pathlib import Path
import queue
import re
import threading
import time
from urllib.parse import urlsplit
from core import Entries
from overlay import OverlayWorker, snapshot

os.environ.setdefault('OPENCV_FFMPEG_CAPTURE_OPTIONS', 'rtsp_transport;tcp')
os.environ.setdefault('OPENCV_FFMPEG_LOGLEVEL', '-8')
LOG = logging.getLogger('analytics')

class ApiWorker(threading.Thread):
    def __init__(self, config):
        super().__init__(daemon=True)
        self.config = config
        self.events = queue.Queue(maxsize=32)
        self.enabled = False
        self.checked = 0
        self.observation = {'available': False, 'people': 0, 'age': 'disabled'}
        self.stop = threading.Event()

    def offer(self, event):
        try:
            self.events.put_nowait((time.monotonic(), event))
        except queue.Full:
            LOG.warning('Event queue full; expired work will not be replayed')

    def active(self):
        return self.enabled and time.monotonic() - self.checked < 5

    def run(self):
        import requests
        url = self.config['server_url'].rstrip('/') + '/api/cctv/analysis/' + self.config['camera_id']
        http = requests.Session()
        http.trust_env = False
        http.headers['Authorization'] = 'Bearer ' + self.config['analysis_token']
        due = 0
        while not self.stop.is_set():
            now = time.monotonic()
            if now >= due:
                due = now + 2
                try:
                    response = http.get(url + '/state', timeout=1.5, allow_redirects=False)
                    response.raise_for_status()
                    self.enabled = response.json()['analysis'] is True
                    self.checked = time.monotonic()
                    if self.enabled:
                        http.post(url + '/observation', json=self.observation, timeout=1.5, allow_redirects=False)
                except Exception:
                    self.enabled = False
                    LOG.warning('Analysis API unavailable; camera work paused')
            try:
                created, event = self.events.get(timeout=.1)
            except queue.Empty:
                continue
            # Keep original UUID and timestamp on retries. Never replay old detections.
            while self.active() and time.monotonic() - created < 3:
                try:
                    response = http.post(url + '/events', json=event, timeout=1, allow_redirects=False)
                    if response.status_code == 200:
                        break
                    if response.status_code < 500:
                        LOG.warning('Event not accepted status=%s', response.status_code)
                        break
                except Exception:
                    pass
                self.stop.wait(.15)
        http.close()

class Reader(threading.Thread):
    def __init__(self, config, api):
        super().__init__(daemon=True)
        self.config, self.api = config, api
        self.latest = None
        self.generation = 0
        self.seq = 0

    def run(self):
        import cv2
        source = 'rtsp://analysis:' + self.config['analysis_token'] + '@127.0.0.1:8554/' + self.config['camera_id'] + '_raw'
        while not self.api.stop.is_set():
            self.latest = None
            if not self.api.active():
                self.api.stop.wait(.5)
                continue
            cap = cv2.VideoCapture(source, cv2.CAP_FFMPEG, [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 3000, cv2.CAP_PROP_READ_TIMEOUT_MSEC, 3000])
            try:
                if not cap.isOpened():
                    self.api.stop.wait(2)
                    continue
                self.generation += 1
                while self.api.active() and not self.api.stop.is_set():
                    ok, frame = cap.read()
                    if not ok:
                        break
                    self.seq += 1
                    self.latest = (frame, self.seq, time.monotonic(), self.generation)
            finally:
                cap.release()
                self.latest = None

def load_config(path):
    p = Path(path)
    if os.name != 'nt' and p.stat().st_mode & 0o077:
        raise ValueError('Use chmod 600 for config')
    c = json.loads(p.read_text())
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', c['camera_id']) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', c['analysis_token']):
        raise ValueError('Invalid camera/token')
    u = urlsplit(c['server_url'])
    if u.username or u.query or u.fragment or u.path not in ('', '/') or not (u.scheme == 'https' or (u.scheme == 'http' and u.hostname in ('127.0.0.1', 'localhost', '::1'))):
        raise ValueError('HTTPS required except loopback')
    roi = c.get('roi', [0, 0, 1, 1])
    if len(roi) != 4 or not (0 <= roi[0] < roi[2] <= 1 and 0 <= roi[1] < roi[3] <= 1):
        raise ValueError('ROI must be normalized [left,top,right,bottom]')
    return c

def run(c):
    import cv2
    from ultralytics import YOLO
    cv2.setNumThreads(2)
    cv2.setLogLevel(0)
    model = YOLO(c.get('model', 'yolo11n.pt'))
    names = model.names
    person_ids = [k for k, v in names.items() if v == 'person']
    if not person_ids:
        raise ValueError('Model must detect person')
    api = ApiWorker(c)
    reader = Reader(c, api)
    overlay = OverlayWorker(c, api)
    entries = Entries(c['camera_id'])
    ctx = mp.get_context('spawn')
    jobs, replies, stop_age = ctx.Queue(maxsize=1), ctx.Queue(maxsize=4), ctx.Event()
    age_proc = None
    age_ready = busy = False
    if c.get('age', {}).get('enabled', False):
        from mivolo_worker import age_worker
        settings = c['age']
        age_proc = ctx.Process(target=age_worker, args=(jobs, replies, stop_age, settings), daemon=True)
        age_proc.start()
    api.start()
    reader.start()
    overlay.start()
    generation = -1
    last_seq = -1
    next_frame = 0
    try:
        while True:
            now = time.monotonic()
            while True:
                try:
                    result = replies.get_nowait()
                except queue.Empty:
                    break
                if result['kind'] == 'ready':
                    age_ready = True
                elif result['kind'] == 'fatal':
                    age_ready = busy = False
                else:
                    busy = False
                    entries.age(result['id'], result['token'], result['age'])
            if age_proc and not age_proc.is_alive():
                age_ready = busy = False
            snap = reader.latest
            if not api.active() or snap is None or now - snap[2] > 2:
                overlay.latest = None
                api.observation = {'available': False, 'people': 0, 'age': 'unavailable'}
                entries.tracks.clear()
                time.sleep(.05)
                continue
            frame, seq, captured, gen = snap
            if seq == last_seq or now < next_frame:
                time.sleep(.01)
                continue
            last_seq, next_frame = seq, now + .1  # Start with at most 10 analysis FPS per camera.
            if gen != generation:
                entries.tracks.clear()
                generation = gen
                for tracker in getattr(model.predictor, 'trackers', []):
                    tracker.reset()
            result = model.track(frame, persist=True, tracker='bytetrack.yaml', classes=person_ids,
                                 imgsz=640, conf=.35, device=c.get('device', 'cpu'), verbose=False)[0]
            # Slow inference must not turn old frames into fresh wake commands.
            if time.monotonic() - captured > 2:
                api.observation = {'available': False, 'people': 0, 'age': 'unavailable'}
                continue
            h, w = frame.shape[:2]
            roi = c.get('roi', [0, 0, 1, 1])
            rows = []
            if result.boxes is not None and result.boxes.id is not None:
                for tid, box in zip(result.boxes.id.int().cpu().tolist(), result.boxes.xyxy.cpu().tolist()):
                    x1, y1, x2, y2 = map(int, box)
                    if roi[0] <= (x1+x2)/2/w <= roi[2] and roi[1] <= y2/h <= roi[3]:
                        rows.append((tid, (max(0,x1), max(0,y1), min(w,x2), min(h,y2))))
            for event in entries.update([tid for tid, _ in rows]):
                api.offer(event)
            if age_ready and not busy:
                for tid, (x1,y1,x2,y2) in rows:
                    state = entries.tracks[tid]
                    if state['event'] and not state['age_sent'] and now-state['attempted']>.4 and x2-x1>=32 and y2-y1>=64:
                        # Skip overlapping person crops instead of assigning another person's age.
                        overlap = any(other != tid and min(x2,b[2])>max(x1,b[0]) and min(y2,b[3])>max(y1,b[1]) for other,b in rows)
                        if overlap:
                            continue
                        try:
                            jobs.put_nowait({'id': tid, 'token': state['event']['event_id'], 'captured': captured, 'crop': frame[y1:y2,x1:x2].copy()})
                            state['attempted'], busy = now, True
                        except queue.Full:
                            pass
                        break
            for event in entries.age_events():
                api.offer(event)
            age_state = 'ready' if age_ready else 'disabled' if age_proc is None else 'unavailable'
            overlay.latest = (captured, snapshot(rows, entries.tracks, w, h, f'{gen}:{seq}', age_state))
            api.observation = {'available': True, 'people': len(rows), 'age': age_state}
    finally:
        api.stop.set()
        stop_age.set()
        if age_proc:
            age_proc.join(3)
            if age_proc.is_alive():
                age_proc.terminate()
                age_proc.join(2)
        reader.join(4)
        api.join(4)
        overlay.join(2)
        for q in (jobs, replies):
            q.cancel_join_thread()
            q.close()

if __name__ == '__main__':
    mp.freeze_support()
    p = argparse.ArgumentParser()
    p.add_argument('--config', required=True)
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO)
    try:
        run(load_config(args.config))
    except KeyboardInterrupt:
        pass
