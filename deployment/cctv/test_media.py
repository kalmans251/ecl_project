"""Real MediaMTX/FFmpeg SRT authentication and payload smoke test (CI only).
Uses synthetic video and throwaway credentials. No cameras or GPUs required.
"""
import http.server
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import urlencode

TOKEN = 'p' * 43
READ = 'r' * 43
PASSPHRASE = 's' * 43
seen = []
class Auth(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', '0'))))
        seen.append(body)
        valid = body.get('path') == 'cctv01_raw' and (
            body.get('action') == 'publish' and body.get('protocol') == 'srt' and body.get('password') == TOKEN or
            body.get('action') == 'read' and body.get('protocol') == 'rtsp' and body.get('password') == READ)
        self.send_response(200 if valid else 401)
        self.end_headers()

server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Auth)
threading.Thread(target=server.serve_forever, daemon=True).start()
processes = []
try:
    with tempfile.TemporaryDirectory() as directory:
        conf = Path(directory) / 'mediamtx.yml'
        conf.write_text(f'''logLevel: warn
authMethod: http
authHTTPAddress: http://127.0.0.1:{server.server_port}/auth
authHTTPExclude: []
api: false
metrics: false
pprof: false
playback: false
rtspAddress: 127.0.0.1:18554
rtspTransports: [tcp]
rtmp: false
hls: false
webrtc: false
moq: false
srtAddress: 127.0.0.1:18890
paths:
  cctv01_raw:
    source: publisher
    overridePublisher: false
    srtPublishPassphrase: {PASSPHRASE}
''')
        mtx = subprocess.Popen([sys.argv[1], str(conf)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        processes.append(mtx)
        time.sleep(1)
        if mtx.poll() is not None:
            raise AssertionError(mtx.stdout.read().decode())
        def publisher(passphrase, token):
            query = urlencode(dict(streamid='publish:cctv01_raw:camera:'+token, passphrase=passphrase, pbkeylen=32, pkt_size=1316))
            p = subprocess.Popen(['ffmpeg','-nostdin','-hide_banner','-loglevel','error','-re','-f','lavfi','-i','testsrc=size=160x120:rate=5','-t','15','-pix_fmt','yuv420p','-c:v','libx264','-threads','1','-preset','ultrafast','-tune','zerolatency','-f','mpegts','srt://127.0.0.1:18890?'+query], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            processes.append(p)
            return p
        # A missing encryption secret must fail even when the auth token is valid.
        bad = publisher('x'*43, TOKEN)
        try:
            bad.wait(timeout=8)
        except subprocess.TimeoutExpired:
            bad.kill();bad.wait()
        assert bad.returncode != 0, 'Wrong encryption key accepted'
        denied = publisher(PASSPHRASE, 'wrong')
        denied.wait(timeout=8)
        assert denied.returncode != 0, 'Wrong publisher credential accepted'
        good = publisher(PASSPHRASE, TOKEN)
        time.sleep(2)
        reader = subprocess.run(['ffmpeg','-nostdin','-hide_banner','-loglevel','error','-rtsp_transport','tcp','-i',f'rtsp://analysis:{READ}@127.0.0.1:18554/cctv01_raw','-frames:v','1','-f','null','-'], capture_output=True, timeout=12)
        assert reader.returncode == 0, reader.stderr.decode()
        assert any(x.get('protocol')=='srt' and x.get('password')==TOKEN for x in seen)
        assert any(x.get('protocol')=='rtsp' and x.get('password')==READ for x in seen)
        print('PASS: encrypted SRT -> authenticated MediaMTX -> authenticated RTSP decoded frame')
finally:
    for p in reversed(processes):
        if p.poll() is None:
            p.terminate()
            try:p.wait(timeout=3)
            except subprocess.TimeoutExpired:p.kill();p.wait()
    server.shutdown()
