"""Validated console controls using the device firmware's protocol.

Requests are transmitted, not acknowledged/applied state. P4 owns policy and
forwards music settings to WROOM. General controls never queue behind a call.
"""
from __future__ import annotations
import threading
from protocol import Command, Frame, Node, Service

HELP = '''  power <id> ac|battery|on|off    select+start power, or start/stop current mode
  projector <id> on|off          projector relay
  led <id> on|off|basic|music     LED enable or mode
  led <id> weather clear|cloudy|rain|snow
  music <id> start|stop|pause|resume|next
  music <id> mode sequential|shuffle|age
  volume <id> <0..100>           shared WROOM music/voice volume (outside calls)
  sleep <id> on|off              enable/disable existing sleep policy
  detection <id> radar|cctv      choose detection source (CCTV input needs server)
  query <id> p4|wroom|s3         request live SYSTEM status
'''


class DeviceControls:
    def __init__(self, bus, railings, voice):
        self.bus, self.railings, self.voice = bus, railings, voice
        self.lock = threading.Lock()

    def execute(self, parts):
        if not parts or parts[0].lower() not in (
                'power', 'projector', 'led', 'music', 'volume', 'sleep', 'detection', 'query', 'ping'):
            return None
        name = parts[0].lower()
        if len(parts) < 3 and not (name == 'ping' and len(parts) == 2):
            raise ValueError('Invalid command; use help for syntax')
        try:
            rail = int(parts[1], 0)
        except ValueError:
            raise ValueError('railing_id must be an integer') from None
        if not 1 <= rail <= 255:
            raise ValueError('railing_id must be 1..255')
        args = [p.lower() for p in parts[2:]]
        frames = []
        def add(service, command, payload=b'', dst=Node.P4):
            frames.append(Frame(rail, Node.PI, dst, service, command, payload))
        def one(mapping):
            if len(args) != 1 or args[0] not in mapping:
                raise ValueError(f'{name}: expected ' + '|'.join(mapping))
            return mapping[args[0]]
        if name == 'power':
            action = one({'ac': 1, 'battery': 2, 'on': Command.START, 'off': Command.STOP})
            if args[0] in ('ac', 'battery'):
                add(Service.POWER, Command.SET, bytes([action]))
                add(Service.POWER, Command.START)
            else:
                add(Service.POWER, action)
        elif name == 'projector':
            add(Service.PROJECTOR, one({'on': Command.START, 'off': Command.STOP}))
        elif name == 'led':
            if len(args) == 2 and args[0] == 'weather':
                weather = {'clear': 0, 'cloudy': 1, 'rain': 2, 'snow': 3}
                if args[1] not in weather:
                    raise ValueError('led weather: expected clear|cloudy|rain|snow')
                add(Service.LED, Command.SET, bytes([2, weather[args[1]]]))
            else:
                action = one({'on': Command.START, 'off': Command.STOP, 'basic': 1, 'music': 3})
                if args[0] in ('basic', 'music'):
                    add(Service.LED, Command.SET, bytes([action]))
                else:
                    add(Service.LED, action)
        elif name == 'music':
            if len(args) == 2 and args[0] == 'mode':
                modes = {'sequential': 1, 'shuffle': 2, 'age': 3}
                if args[1] not in modes:
                    raise ValueError('music mode: expected sequential|shuffle|age')
                add(Service.MUSIC, Command.SET, bytes([1, modes[args[1]]]))
            else:
                add(Service.MUSIC, one({'start': Command.START, 'stop': Command.STOP,
                    'pause': Command.PAUSE, 'resume': Command.RESUME, 'next': Command.NEXT}))
        elif name == 'volume':
            if len(args) != 1:
                raise ValueError('volume: expected 0..100')
            try:
                value = int(args[0])
            except ValueError:
                raise ValueError('volume: expected 0..100') from None
            if not 0 <= value <= 100:
                raise ValueError('volume: expected 0..100')
            add(Service.MUSIC, Command.SET, bytes([3, value]))
        elif name == 'sleep':
            add(Service.SLEEP, one({'on': Command.START, 'off': Command.STOP}))
        elif name == 'detection':
            add(Service.DETECTION, Command.SET, bytes([one({'radar': 0, 'cctv': 1})]))
        elif name == 'query':
            add(Service.SYSTEM, Command.STATUS_REQUEST,
                dst=one({'p4': Node.P4, 'wroom': Node.WROOM, 's3': Node.S3}))
        elif name == 'ping':
            if args:
                raise ValueError('ping: expected only railing_id')
            add(Service.SYSTEM, Command.PING)
        with self.lock:
            for frame in frames:
                self._check_idle()
                self.bus.send_frame(frame)
        return f'Request sent rail={rail}: {" ".join(parts)} ({len(frames)} frame(s)); device application not confirmed'

    def _check_idle(self):
        if self.voice.control_paused():
            raise RuntimeError('PTT/control confirmation unresolved; retry PTT or hangup first')
        if any(s['call']['active'] or s['emergency']['active']
               for s in self.railings.snapshot().values()):
            raise RuntimeError('General controls blocked while a call/emergency is active on the PLC bus')


def device_status(frame):
    if frame.service != Service.SYSTEM or frame.command != Command.STATUS_RESPONSE:
        return None
    try:
        source = Node(frame.src).name
    except ValueError:
        source = f'0x{int(frame.src):02x}'
    detail = f'payload={frame.payload.hex(" ")}'
    if frame.src == Node.P4 and len(frame.payload) == 1:
        detail = f'alive={frame.payload[0]}'
    elif frame.src == Node.WROOM and len(frame.payload) == 4:
        alive, sd, music, rail = frame.payload
        state = {0: 'idle', 1: 'playing', 2: 'paused'}.get(music, str(music))
        detail = f'alive={alive} sd_mounted={sd} music={state} device_rail={rail}'
    return f'[DEVICE STATUS] rail={frame.railing_id} node={source} {detail}'
