"""Protocol test client. It receives messages but never writes to PLC or claims PLC_SENT."""
import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
from websockets.asyncio.client import connect


async def run(args):
    token = os.environ['MONITOR_GATEWAY_TOKEN']
    async with connect(args.url, additional_headers={'Authorization': 'Bearer ' + token},
                       max_size=4096, ping_interval=20, ping_timeout=20) as socket:
        print('SIMULATION: connected; no Pi/P4 is controlled', flush=True)
        async for raw in socket:
            message = json.loads(raw)
            print(json.dumps(message, ensure_ascii=False), flush=True)
            if message.get('type') in ('cctv.enter', 'cctv.age'):
                expires = datetime.fromisoformat(message['expires_at'].replace('Z', '+00:00'))
                status = 'RECEIVED' if expires > datetime.now(timezone.utc) else 'EXPIRED'
                await socket.send(json.dumps(dict(version=1, type='ack',
                                                  message_id=message['message_id'], status=status)))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='ws://127.0.0.1:8080/ws/gateways/gateway-01')
    args = parser.parse_args()
    if not args.url.startswith('wss://') and not args.url.startswith('ws://127.0.0.1:'):
        parser.error('Use WSS except for loopback testing')
    if not os.environ.get('MONITOR_GATEWAY_TOKEN'):
        parser.error('Set MONITOR_GATEWAY_TOKEN')
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass
