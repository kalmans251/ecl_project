"""Round-robin music snapshots; one PLC reader, no unsolicited catalog traffic."""
from control_remote import OPERATIONS
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
    """Authenticated music state and bounded device controls."""
    def __init__(self, url, token, remote=None, calls=None):
        validate_url(url)
        if not token:
            raise ValueError('Set MONITOR_GATEWAY_TOKEN')
        self.url, self.token = url, token
        self.remote = remote
        self.calls = calls
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
                        if self.calls: self.calls.disconnect()
                        if self.command_task:
                            await self.command_task
                        if self.calls: self.calls.disconnect()
            except Exception as exc:
                LOG.warning('Music monitoring disconnected (%s); retrying', type(exc).__name__)
                for _ in range(20):
                    if self.stop.is_set():
                        return
                    await asyncio.sleep(.1)

    async def _connection(self, ws, alive):
        from call_remote import OPERATIONS as CALLS
        self.command_task = None
        incoming = asyncio.Queue(maxsize=2)
        async def execute(message, handler):
            try:
                result = await asyncio.to_thread(handler.handle, message,
                    lambda: alive.is_set() and not self.stop.is_set())
                if alive.is_set() and not self.stop.is_set():
                    await ws.send(json.dumps(result, ensure_ascii=False))
            except Exception as exc:
                if self.calls and handler is self.calls:
                    self.calls.disconnect()
                LOG.warning('Gateway command result unavailable (%s)', type(exc).__name__)
        async def sender():
            while not self.stop.is_set():
                messages = self.drain() + (self.calls.drain() if self.calls else [])
                for message in messages:
                    await ws.send(json.dumps(message, ensure_ascii=False))
                await asyncio.sleep(.02)
        async def audio_worker():
            while True:
                at,message = await incoming.get()
                if self.calls and alive.is_set() and time.monotonic()-at<.4:
                    await asyncio.to_thread(self.calls.receive, message)
        async def receiver():
            while not self.stop.is_set():
                raw = await ws.recv()
                message = json.loads(raw)
                if message.get('type')=='voice.pause' and self.calls:
                    current=self.calls.current
                    if current and message.get('call_id')==current[0]: self.calls.disconnect()
                    continue
                if message.get('type')=='voice' and self.calls:
                    if not incoming.full(): incoming.put_nowait((time.monotonic(),message))
                    continue
                if message.get('type')=='command' and message.get('operation')=='call.start' and not self.calls:
                    LOG.warning('Web call not started: restart main.py with --web-voice')
                    await ws.send(json.dumps(dict(version=1,type='call_result',
                        message_id=message['message_id'],status='NOT_STARTED',
                        data=dict(call_id=message.get('call_id'),railing_id=message.get('railing_id'),
                                  epoch=message['message_id']))))
                    continue
                handler = self.calls if message.get('type') == 'command' and message.get('operation') in CALLS else self.remote
                supported = CALLS if handler is self.calls and self.calls else ({'music.list','music.play','music.seek'} | OPERATIONS)
                if ((message.get('type')=='command' and message.get('operation') in supported)
                        or message.get('type') in ('cctv.enter','cctv.age')) and handler:
                    if self.command_task and not self.command_task.done():
                        await ws.send(json.dumps(dict(version=1,type='ack',message_id=message['message_id'],status='BUSY')))
                    else:
                        self.command_task = asyncio.create_task(execute(message,handler))
                elif message.get('type') in ('command','cctv.enter','cctv.age'):
                    await ws.send(json.dumps(dict(version=1,type='ack',message_id=message['message_id'],status='FAILED')))
        tasks = [asyncio.create_task(fn()) for fn in (sender,receiver,audio_worker)]
        try:
            done,_ = await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED)
            for task in done: task.result()
        finally:
            alive.clear()
            if self.calls: self.calls.disconnect()
            for task in tasks: task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(10)
