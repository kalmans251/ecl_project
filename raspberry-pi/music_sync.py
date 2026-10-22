"""Round-robin music snapshots; one PLC reader, no unsolicited catalog traffic."""
import asyncio
from datetime import datetime, timezone
import json
import logging
import threading
import time
from urllib.parse import urlparse
from music_info import status

LOG = logging.getLogger('music.sync')


def validate_url(url):
    parsed = urlparse(url)
    if (not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment
            or not parsed.path.startswith('/ws/gateways/')
            or not parsed.path[len('/ws/gateways/'):]
            or '/' in parsed.path[len('/ws/gateways/'):]
            or not (parsed.scheme == 'wss' or
                    (parsed.scheme == 'ws' and parsed.hostname in ('127.0.0.1', 'localhost', '::1')))):
        raise ValueError('Use wss://host/ws/gateways/<id> (ws only on loopback)')


class MusicSync:
    def __init__(self, controls, rails, interval=2.0, publish=None):
        self.controls, self.rails = controls, tuple(rails)
        self.interval, self.publish = interval, publish
        if not self.rails or not 1 <= interval <= 30:
            raise ValueError('Music interval must be 1..30 seconds and rails must be configured')
        self.fresh_ms = min(120000, max(10000, int(len(self.rails) * (interval + .6) * 2000)))
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.states = {}
        self.thread = None

    def sample(self, rail):
        message = dict(version=1, type='music_state', railing_id=rail,
                       observed_at=datetime.now(timezone.utc).isoformat(), fresh_ms=self.fresh_ms)
        try:
            data = status(self.controls, rail, background=True)
            message['state'] = dict(available=True, state=data['state'], filename=data['filename'],
                                    position_ms=data['position_ms'],duration_ms=data['duration_ms'],
                                    playback_id=data['playback_id'],seekable=data['seekable'])
        except (RuntimeError, ValueError, OSError):
            message['state'] = dict(available=False)
        # Timestamp after receiving confirmation, not before waiting for PLC.
        message['observed_at'] = datetime.now(timezone.utc).isoformat()
        with self.lock:
            self.states[rail] = message
        if self.publish:
            self.publish(message)
        return message

    def snapshot(self):
        with self.lock:
            return json.loads(json.dumps(self.states))

    def start(self):
        self.thread = threading.Thread(target=self._run, name='music-poll', daemon=True)
        self.thread.start()

    def _run(self):
        while not self.stop.is_set():
            for rail in self.rails:
                if self.stop.wait(self.interval):
                    return
                self.sample(rail)

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(2)


class MusicPublisher:
    """Authenticated music state and bounded list/play commands."""
    def __init__(self, url, token, remote=None):
        validate_url(url)
        if not token:
            raise ValueError('Set MONITOR_GATEWAY_TOKEN')
        self.url, self.token = url, token
        self.remote = remote
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.pending = {}
        self.thread = None

    def publish(self, message):
        with self.lock:
            # Bounded to one latest snapshot per configured railing.
            self.pending[message['railing_id']] = (time.monotonic(), message)

    def drain(self):
        with self.lock:
            values = list(self.pending.values())
            self.pending.clear()
        return [m for t, m in values if time.monotonic() - t < 5]

    def start(self):
        from websockets.asyncio.client import connect  # fail at startup if optional dependency absent
        self.thread = threading.Thread(target=lambda: asyncio.run(self._run(connect)),
                                       name='music-publisher', daemon=True)
        self.thread.start()

    async def _run(self, connect):
        while not self.stop.is_set():
            try:
                async with connect(self.url, additional_headers={'Authorization': 'Bearer ' + self.token},
                                   max_size=4096, open_timeout=5, close_timeout=1,
                                   ping_interval=20, ping_timeout=20) as ws:
                    LOG.info('Music monitoring connection established')
                    alive = threading.Event(); alive.set()
                    try:
                        await self._connection(ws, alive)
                    finally:
                        alive.clear()
                        if self.command_task:
                            await self.command_task
            except Exception as exc:
                LOG.warning('Music monitoring disconnected (%s); retrying', type(exc).__name__)
                for _ in range(20):
                    if self.stop.is_set():
                        return
                    await asyncio.sleep(.1)

    async def _connection(self, ws, alive):
        self.command_task = None
        async def execute(message):
            try:
                result = await asyncio.to_thread(self.remote.handle, message,
                    lambda: alive.is_set() and not self.stop.is_set())
                if alive.is_set() and not self.stop.is_set():
                    await ws.send(json.dumps(result, ensure_ascii=False))
            except Exception as exc:
                # Journal remains uncertain; never retry automatically.
                LOG.warning('Music command result unavailable (%s)', type(exc).__name__)
        while not self.stop.is_set():
            for message in self.drain():
                await ws.send(json.dumps(message, ensure_ascii=False))
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=.5)
            except asyncio.TimeoutError:
                continue
            message = json.loads(raw)
            if message.get('type') == 'command' and message.get('operation') in ('music.list','music.play','music.seek') and self.remote:
                if self.command_task and not self.command_task.done():
                    await ws.send(json.dumps(dict(version=1,type='ack',message_id=message['message_id'],status='BUSY')))
                else:
                    self.command_task = asyncio.create_task(execute(message))
            elif message.get('type') in ('command','cctv.enter','cctv.age'):
                await ws.send(json.dumps(dict(version=1,type='ack',message_id=message['message_id'],status='FAILED')))

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(10)
