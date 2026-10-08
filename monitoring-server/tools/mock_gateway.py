"""Protocol simulator. Never connects to PLC; --simulate-device emits fake device results."""
import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
from websockets.asyncio.client import connect


async def run(args):
    token = os.environ['MONITOR_GATEWAY_TOKEN']
    state = dict(volume=20, power='ac', power_on=True, led='basic', projector=False,
                 sleep=False, music='stopped', music_mode='sequential', detection='radar',
                 emergency=False, left_watt=12.5, right_watt=13.2, battery_percent=76,
                 radar=[dict(x=0.3, y=2.1)], detection_count=1)
    async with connect(args.url, additional_headers={'Authorization': 'Bearer ' + token},
                       max_size=4096, ping_interval=20, ping_timeout=20) as socket:
        print('SIMULATION: no Pi/P4 is controlled', flush=True)

        async def telemetry():
            while True:
                await socket.send(json.dumps(dict(version=1, type='telemetry', railing_id=args.railing,
                                                 observed_at=datetime.now(timezone.utc).isoformat(), state=state)))
                await asyncio.sleep(2)

        task = asyncio.create_task(telemetry()) if args.simulate_device else None
        try:
            async for raw in socket:
                message = json.loads(raw)
                print(json.dumps(message, ensure_ascii=False), flush=True)
                if message.get('type') not in ('cctv.enter', 'cctv.age', 'command'):
                    continue
                expires = datetime.fromisoformat(message['expires_at'].replace('Z', '+00:00'))
                status = 'RECEIVED' if expires > datetime.now(timezone.utc) else 'EXPIRED'
                if args.simulate_device and status != 'EXPIRED':
                    op, value = message.get('operation'), message.get('value')
                    status = 'APPLIED' if op in ('volume', 'music.stop', 'call.start', 'call.end', 'ptt.on', 'ptt.off') else 'PLC_SENT'
                    if op in ('led.basic_pattern', 'led.music_pattern'):
                        state['led'] = 'basic' if op == 'led.basic_pattern' else 'music'
                    elif op == 'volume':
                        state['volume'] = int(value)
                    elif op == 'power':
                        state['power' if value in ('ac', 'battery') else 'power_on'] = value if value in ('ac', 'battery') else value == 'on'
                    elif op in ('projector', 'sleep'):
                        state[op] = value == 'on'
                    elif op in ('led', 'weather', 'detection'):
                        state['led_enabled' if op == 'led' and value in ('on', 'off') else op] = value == 'on' if value in ('on', 'off') else value
                    elif op == 'music.mode':
                        state['music_mode'] = value
                    elif op in ('music.start', 'music.resume', 'music.stop', 'music.pause'):
                        state['music'] = {'music.start': 'playing', 'music.resume': 'playing', 'music.stop': 'stopped', 'music.pause': 'paused'}[op]
                await socket.send(json.dumps(dict(version=1, type='ack', message_id=message['message_id'], status=status)))
        finally:
            if task:
                task.cancel()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='ws://127.0.0.1:8080/ws/gateways/gateway-01')
    parser.add_argument('--simulate-device', action='store_true', help='Emit simulated telemetry and APPLIED/PLC_SENT acknowledgments (not hardware proof)')
    parser.add_argument('--railing', type=int, default=1)
    args = parser.parse_args()
    if not args.url.startswith('wss://') and not args.url.startswith('ws://127.0.0.1:'):
        parser.error('Use WSS except for loopback testing')
    if not 1 <= args.railing <= 255 or not os.environ.get('MONITOR_GATEWAY_TOKEN'):
        parser.error('Set MONITOR_GATEWAY_TOKEN and a railing number in 1..255')
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass
