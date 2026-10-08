"""Validated console controls using the device firmware's protocol.

Music STOP and volume require correlated WROOM application results. Other
requests confirm transmission only. P4 owns policy and
forwards music settings to WROOM. General controls never queue behind a call.
"""
from __future__ import annotations
import threading
import secrets
import time
from protocol import Command, Frame, Node, Service

HELP = '''  power <id> ac|battery|on|off    select+start power, or start/stop current mode
  projector <id> on|off          projector relay
  led <id> on|off|basic|music     LED enable or mode
  led <id> basic [1..6] | music [1..3]  select animation
  led <id> weather clear|cloudy|rain|snow
  music <id> start|stop|pause|resume|next
  music <id> mode sequential|shuffle|age
  volume <id> <0..100>           shared WROOM music/voice volume (outside calls)
  sleep <id> on|off              enable/disable existing sleep policy
  detection <id> radar|cctv      choose detection source (CCTV input needs server)
  cctv <id> enter <seq>          inject a new-person event (CCTV mode)\n  cctv <id> age <seq> 10|20|30|40|keep\n                                inject matching age result; keep preserves group\n  query <id> p4|wroom|s3         request live SYSTEM status
'''


class DeviceControls:
    def __init__(self, bus, railings, voice, ack_timeout=3.0):
        self.bus, self.railings, self.voice = bus, railings, voice
        self.lock = threading.Lock()
        self.condition = threading.Condition()
        self.ack_timeout = ack_timeout
        self.request_id = secrets.randbits(32)
        self.pending = None
        self.result = None

    def execute(self, parts):
        if not parts or parts[0].lower() not in (
                'power', 'projector', 'led', 'music', 'volume', 'sleep', 'detection', 'query', 'ping', 'cctv'):
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
            if len(args) == 2 and args[0] in ('basic', 'music'):
                count = 6 if args[0] == 'basic' else 3
                if args[1] not in {str(n) for n in range(1, count + 1)}:
                    raise ValueError(f'led {args[0]}: expected 1..{count}')
                add(Service.LED, Command.SET, bytes([1 if args[0] == 'basic' else 3, int(args[1]) - 1]))
            elif len(args) == 2 and args[0] == 'weather':
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
        elif name == 'cctv':
            if (not args or args[0] not in ('enter', 'age')
                    or len(args) != (2 if args[0] == 'enter' else 3)):
                raise ValueError('cctv: use enter <seq> or age <seq> 10|20|30|40|keep')
            try:
                seq = int(args[1], 0)
            except ValueError:
                raise ValueError('cctv: seq must be an integer 0..4294967295') from None
            if not 0 <= seq <= 0xffffffff:
                raise ValueError('cctv: seq must be 0..4294967295')
            token = seq.to_bytes(4, 'big')
            if args[0] == 'enter':
                add(Service.DETECTION, Command.DATA, bytes([1]) + token)
            else:
                ages = {'10': 1, '20': 2, '30': 3, '40': 4, 'keep': 0xff}
                if args[2] not in ages:
                    raise ValueError('cctv age: expected 10|20|30|40|keep')
                add(Service.DETECTION, Command.DATA, bytes([2]) + token + bytes([ages[args[2]]]))
        elif name == 'query':
            add(Service.SYSTEM, Command.STATUS_REQUEST,
                dst=one({'p4': Node.P4, 'wroom': Node.WROOM, 's3': Node.S3}))
        elif name == 'ping':
            if args:
                raise ValueError('ping: expected only railing_id')
            add(Service.SYSTEM, Command.PING)
        confirmed = name == 'volume' or (name == 'music' and args == ['stop'])
        with self.lock:
            if confirmed:
                self._check_idle()
                original = frames[0]
                self.request_id = (self.request_id + 1) & 0xffffffff
                token = self.request_id.to_bytes(4, 'big')
                with self.condition:
                    self.pending = (rail, token, original.command,
                                    original.payload[-1] if name == 'volume' else 0)
                    self.result = None
                try:
                    self.bus.send_frame(Frame(rail, Node.PI, Node.P4, Service.MUSIC,
                        Command.APPLY, token + bytes([original.command]) + original.payload))
                    deadline = time.monotonic() + self.ack_timeout
                    with self.condition:
                        while self.result is None:
                            remaining = deadline - time.monotonic()
                            if remaining <= 0:
                                raise TimeoutError('Device application confirmation timed out; '
                                                   'application state is unknown')
                            self.condition.wait(remaining)
                        status, detail = self.result
                    if status != 0:
                        reason = 'rejected' if status == 1 else 'execution failed'
                        raise RuntimeError(f'Device application {reason} rail={rail}')
                    return f'Applied rail={rail}: {" ".join(parts)} (WROOM confirmed)'
                finally:
                    with self.condition:
                        self.pending = None
                        self.result = None
            for frame in frames:
                self._check_idle()
                self.bus.send_frame(frame)
        return f'Request sent rail={rail}: {" ".join(parts)} ({len(frames)} frame(s)); device application not confirmed'

    def handle_frame(self, frame):
        if (frame.dst != Node.PI or frame.src not in (Node.P4, Node.WROOM)
                or frame.service != Service.MUSIC or frame.command != Command.APPLY_RESULT
                or len(frame.payload) != 7):
            return False
        token, op, status, detail = frame.payload[:4], *frame.payload[4:]
        if status not in (0, 1, 2):
            return False
        with self.condition:
            pending = self.pending
            if pending is None or (frame.railing_id, token, op) != pending[:3]:
                return True # delayed/foreign response cannot confirm a new request
            if status == 0 and (frame.src != Node.WROOM or detail != pending[3]):
                return True
            self.result = (status, detail)
            self.condition.notify_all()
        return True

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
