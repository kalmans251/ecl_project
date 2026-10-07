"""Send synthetic analytics to the server; this does not perform video analysis."""
import argparse
from datetime import datetime, timezone
import json
import os
from urllib.request import Request, urlopen
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:8080')
    parser.add_argument('--camera', default='cctv01')
    parser.add_argument('--event-id', default=None, help='Reuse the enter UUID for age')
    parser.add_argument('--type', choices=['enter', 'age'], default='enter')
    parser.add_argument('--age-group', choices=['10', '20', '30', '40', 'keep'])
    args = parser.parse_args()
    if args.type == 'age' and (not args.event_id or not args.age_group):
        parser.error('age requires --event-id and --age-group')
    if args.type == 'enter' and args.age_group:
        parser.error('enter does not accept age-group')
    token = os.environ.get('MONITOR_ANALYTICS_TOKEN')
    if not token:
        parser.error('Set MONITOR_ANALYTICS_TOKEN')
    if not args.url.startswith('https://') and not args.url.startswith('http://127.0.0.1:'):
        parser.error('Use HTTPS except for loopback testing')
    event_id = str(uuid.UUID(args.event_id)) if args.event_id else str(uuid.uuid4())
    body = dict(camera_id=args.camera, event_id=event_id, type=args.type,
                observed_at=datetime.now(timezone.utc).isoformat())
    if args.age_group:
        body['age_group'] = args.age_group
    print('event_id:', event_id)
    request = Request(args.url.rstrip('/') + '/api/analytics/events',
                      data=json.dumps(body).encode(),
                      headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
    with urlopen(request, timeout=10) as response:
        print(response.read().decode())


if __name__ == '__main__':
    main()
