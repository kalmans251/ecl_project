"""Outbound WSS control with a bounded FFmpeg lease. No remote shell or URLs."""
import argparse
import asyncio
import contextlib
import json
import logging
import os
from pathlib import Path
import re
import signal
import subprocess
import time
from urllib.parse import urlsplit, urlencode
from camera_time import validate_config, time_sync_loop

LOG = logging.getLogger('camera')

def load_config(path):
    path = Path(path)
    if os.name != 'nt' and path.stat().st_mode & 0o077:
        raise ValueError('Config must be owner-only (chmod 600)')
    c = json.loads(path.read_text())
    camera = c['camera_id']
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', camera):
        raise ValueError('Invalid camera ID')
    ws = urlsplit(c['control_url'])
    if ws.scheme != 'wss' or not ws.hostname or ws.username or ws.query or ws.fragment or ws.path != '/ws/cameras/' + camera:
        raise ValueError('Use an authenticated wss camera endpoint')
    for key in ('control_token', 'publish_token'):
        if not re.fullmatch(r'[A-Za-z0-9_-]{43}', c[key]):
            raise ValueError('Invalid token format')
    rtsp = urlsplit(c['camera_url'])
    if rtsp.scheme != 'rtsp' or not rtsp.hostname:
        raise ValueError('Camera must use a local RTSP URL')
    if not re.fullmatch(r'[A-Za-z0-9.-]+', c['server_host']):
        raise ValueError('Invalid SRT host')
    if not re.fullmatch(r'[A-Za-z0-9_-]{32,79}', c['srt_passphrase']):
        raise ValueError('Use a random SRT passphrase (32..79 URL-safe characters)')
    validate_config(c)
    return c

def rtsp_timeout_option():
    """RTSP options differ between FFmpeg builds; rw_timeout is not portable."""
    try:
        result = subprocess.run(['ffmpeg', '-hide_banner', '-h', 'demuxer=rtsp'],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=3, check=True)
    except (OSError, subprocess.SubprocessError):
        return None
    # Older builds also have a 'timeout' in seconds for listening. Prefer
    # stimeout there, and only accept modern timeout when units are explicit.
    if re.search(r'(?m)^\s*-stimeout\s', result.stdout):
        return '-stimeout'
    if re.search(r'(?mi)^\s*-timeout\s[^\n]*microseconds', result.stdout):
        return '-timeout'
    # The existing no-progress watchdog still terminates stalled FFmpeg.
    return None

def ffmpeg_args(c, timeout_option='-timeout'):
    if timeout_option not in (None, '-timeout', '-stimeout'):
        raise ValueError('Unsupported RTSP timeout option')
    query = urlencode({'streamid': f"publish:{c['camera_id']}_raw:camera:{c['publish_token']}",
                       'pkt_size': 1316, 'passphrase': c['srt_passphrase'], 'pbkeylen': 32})
    return ['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-progress', 'pipe:1',
            '-rtsp_transport', 'tcp', *([timeout_option, '10000000'] if timeout_option else []), '-i', c['camera_url'],
            '-map', '0:v:0', '-c:v', 'copy', '-an', '-f', 'mpegts',
            f"srt://{c['server_host']}:8890?{query}"]

class Supervisor:
    def __init__(self, config, clock=time.monotonic, timeout_option='-timeout'):
        self.config, self.clock = config, clock
        self.timeout_option = timeout_option
        self.deadline = 0
        self.wanted = False
        self.revision = None
        self.proc = None
        self.progress_task = None
        self.last_progress = 0
        self.started = 0
        self.retry_at = 0
        self.state = 'stopped'

    def desired(self, msg):
        if set(msg) != {'version', 'type', 'camera_id', 'revision', 'stream', 'lease_seconds'}:
            raise ValueError('Invalid control fields')
        if (msg['version'] != 1 or msg['type'] != 'desired' or msg['camera_id'] != self.config['camera_id']
                or type(msg['stream']) is not bool or type(msg['lease_seconds']) is not int
                or not 1 <= msg['lease_seconds'] <= 15
                or not re.fullmatch(r'[a-f0-9-]{36}', msg['revision'])):
            raise ValueError('Invalid control values')
        self.wanted = msg['stream']
        self.revision = msg['revision']
        self.deadline = self.clock() + msg['lease_seconds']

    async def progress(self, proc):
        last = -1
        while line := await proc.stdout.readline():
            if line.startswith(b'out_time_us='):
                with contextlib.suppress(ValueError):
                    value = int(line.split(b'=', 1)[1])
                    if value > last:
                        last = value
                        self.last_progress = self.clock()
                        self.state = 'streaming'

    async def stop(self):
        proc, self.proc = self.proc, None
        if proc and proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), 3)
            except asyncio.TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    proc.kill()
                await proc.wait()
        if self.progress_task:
            self.progress_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.progress_task
            self.progress_task = None
        self.state = 'stopped'

    async def tick(self):
        now = self.clock()
        if not self.wanted or now >= self.deadline:
            await self.stop()
            return
        if self.proc and (self.proc.returncode is not None or now - max(self.last_progress, self.started) > 15):
            await self.stop()
            self.state = 'error'
            self.retry_at = now + 3
        if self.proc is None and now >= self.retry_at:
            try:
                # Credentials are never passed through a shell or written to logs.
                self.proc = await asyncio.create_subprocess_exec(*ffmpeg_args(self.config, self.timeout_option),
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
                self.started, self.last_progress, self.state = now, 0, 'starting'
                self.progress_task = asyncio.create_task(self.progress(self.proc))
            except OSError:
                self.state, self.retry_at = 'error', now + 5

async def run(config):
    from websockets.asyncio.client import connect
    timeout_option = await asyncio.to_thread(rtsp_timeout_option)
    LOG.info('RTSP timeout option: %s', timeout_option or 'watchdog only')
    supervisor = Supervisor(config, timeout_option=timeout_option)
    async def watchdog():
        while True:
            await supervisor.tick()
            await asyncio.sleep(.25)
    task = asyncio.create_task(watchdog())
    try:
        while True:
            try:
                async with connect(config['control_url'], additional_headers={'Authorization': 'Bearer ' + config['control_token']},
                                   open_timeout=10, close_timeout=3, max_size=1024, max_queue=2, ping_interval=20, ping_timeout=20) as ws:
                    LOG.info('Control connected camera=%s', config['camera_id'])
                    async for raw in ws:
                        supervisor.desired(json.loads(raw))
                        await ws.send(json.dumps({'version': 1, 'type': 'status', 'revision': supervisor.revision, 'state': supervisor.state}))
            except asyncio.CancelledError:
                raise
            except Exception:
                # Exception messages from transports may contain URLs/credentials.
                LOG.warning('Control disconnected; retrying')
            finally:
                supervisor.wanted = False
            await asyncio.sleep(3)
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        await supervisor.stop()

async def main_async(config):
    task = asyncio.create_task(run(config))
    clock_task = asyncio.create_task(time_sync_loop(config))
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, task.cancel)
    try:
        with contextlib.suppress(asyncio.CancelledError):
            await task
    finally:
        clock_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await clock_task

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    asyncio.run(main_async(load_config(args.config)))
