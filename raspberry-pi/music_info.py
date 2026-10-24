"""On-demand, correlated WROOM music reads. Never stream a catalog unsolicited."""
import time
from contextlib import ExitStack, nullcontext
from protocol import Command, Frame, Node, Service

GROUPS = {'default': 0, '10': 1, '20': 2, '30': 3, '40': 4}


def request(controls, rail, operation, payload=b'', *, background=False, timeout=None, guard=None):
    # Release bus ownership between tracks so event polling can run.
    with ExitStack() as stack:
        if background:
            for lock in (controls.lock, controls.bus.transaction()):
                if not lock.acquire(blocking=False):
                    raise RuntimeError('PLC busy; background music query skipped')
                stack.callback(lock.release)
        else:
            stack.enter_context(controls.lock)
            stack.enter_context(getattr(controls.bus, 'transaction', nullcontext)())
        if guard:
            guard()
        controls._check_idle()
        controls.request_id = (controls.request_id + 1) & 0xffffffff
        token = controls.request_id.to_bytes(4, 'big')
        with controls.condition:
            controls.pending = (rail, token, operation, Service.MUSIC, Node.WROOM, None)
            controls.result = None
        try:
            controls.bus.send_frame(Frame(rail, Node.PI, Node.P4, Service.MUSIC,
                Command.APPLY, token + bytes([operation]) + payload))
            deadline = time.monotonic() + (controls.ack_timeout if timeout is None else timeout)
            with controls.condition:
                while controls.result is None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError('Music request timed out; device state unknown; no automatic retry')
                    controls.condition.wait(remaining)
                status, data, source = controls.result
            if status != 0 or source != Node.WROOM:
                raise RuntimeError('Music request rejected/failed; check catalog, music session and pause/sleep policy')
            return data
        finally:
            with controls.condition:
                controls.pending = controls.result = None


def status(controls, rail, *, background=False):
    data = request(controls, rail, Command.MUSIC_TIMELINE, background=background,
                   timeout=0.6 if background else None)
    if len(data)<15 or data[0]>2 or data[13]>1 or data[14]>95 or len(data)!=15+data[14]:
        raise ValueError('Malformed music timeline')
    duration=int.from_bytes(data[5:9],'big')
    return dict(railing_id=rail,state=('idle','playing','paused')[data[0]],
                position_ms=int.from_bytes(data[1:5],'big'),duration_ms=duration or None,
                playback_id=int.from_bytes(data[9:13],'big'),seekable=bool(data[13]),
                filename=data[15:].decode('utf-8',errors='replace') or None,
                position_basis='MP3 frames / PCM submitted to I2S')


def seek(controls, rail, playback_id, position_ms, *, guard=None):
    if type(playback_id) is not int or not 1<=playback_id<=0xffffffff or type(position_ms) is not int or not 0<=position_ms<=0xffffffff:
        raise ValueError('Invalid playback ID or position')
    payload=playback_id.to_bytes(4,'big')+position_ms.to_bytes(4,'big')
    data=request(controls,rail,Command.MUSIC_SEEK,payload,guard=guard,timeout=8.0)
    if len(data)!=9 or data[0]!=1 or data[1:5]!=payload[:4]:
        raise ValueError('Seek confirmation does not match current playback')
    return dict(railing_id=rail,state='playing',device_application_confirmed=True,
                playback_id=playback_id,position_ms=int.from_bytes(data[5:9],'big'))


def catalog(controls, rail, group=None):
    controls.music_catalogs.pop(rail, None)
    data = request(controls, rail, Command.MUSIC_CATALOG)
    if len(data) != 14:
        raise ValueError('Malformed music catalog')
    version = data[:4]
    counts = [int.from_bytes(data[4+g*2:6+g*2], 'big') for g in range(5)]
    if any(n > 32 for n in counts):
        raise ValueError('Music catalog exceeds firmware limits')
    tracks = []
    for label, g in GROUPS.items():
        if group is not None and label != group:
            continue
        for index in range(counts[g]):
            identity = version + bytes([g]) + index.to_bytes(2, 'big')
            item = request(controls, rail, Command.MUSIC_TRACK, identity)
            if (len(item) < 8 or item[:7] != identity or not 1 <= item[7] <= 95
                    or len(item) != 8 + item[7]):
                raise ValueError('Malformed or changed music track response; refresh list')
            tracks.append({'group': label, 'index': index,
                           'filename': item[8:].decode('utf-8', errors='replace')})
    # Detect a catalog replaced during the last track exchange, too.
    final = request(controls, rail, Command.MUSIC_CATALOG)
    if final != data:
        raise RuntimeError('Music catalog changed during query; refresh list')
    result = {'railing_id': rail, 'catalog_version': int.from_bytes(version, 'big'),
              'counts': dict(zip(GROUPS, counts)), 'tracks': tracks}
    controls.music_catalogs[rail] = result
    return result


def play(controls, rail, group, index, *, expected_version=None, guard=None):
    if group not in GROUPS or not index.isascii() or not index.isdecimal() or not 0 <= int(index) < 32:
        raise ValueError('music play: group default|10|20|30|40, zero-based index 0..31')
    index = int(index)
    listing = controls.music_catalogs.get(rail)
    if not listing:
        raise ValueError('Run music <id> list first in this process')
    if expected_version is not None and listing['catalog_version'] != expected_version:
        raise ValueError('Catalog version changed; refresh list')
    track = next((t for t in listing['tracks'] if t['group'] == group and t['index'] == index), None)
    if track is None:
        raise ValueError('Track was not in the displayed list; refresh the required group')
    identity = listing['catalog_version'].to_bytes(4, 'big') + bytes([GROUPS[group]]) + index.to_bytes(2, 'big')
    data = request(controls, rail, Command.MUSIC_PLAY, identity, guard=guard, timeout=8.0)
    if len(data)!=8 or data[0] not in (1,2) or data[1:]!=identity:
        raise ValueError('Selected-track confirmation does not match; playback state unknown')
    return {'railing_id': rail, 'state': 'playing' if data[0]==1 else 'paused', 'device_application_confirmed': True,
            'catalog_version': listing['catalog_version'], **track}


def page(controls, rail, group, offset=0, *, guard=None):
    """Eight tracks at a time; release PLC between each correlated read."""
    if group not in GROUPS or offset not in (0, 8, 16, 24):
        raise ValueError('Invalid catalog page')
    previous = controls.music_catalogs.pop(rail, None)
    data = request(controls, rail, Command.MUSIC_CATALOG, guard=guard)
    if len(data) != 14:
        raise ValueError('Malformed music catalog')
    version = data[:4]
    counts = [int.from_bytes(data[4+g*2:6+g*2], 'big') for g in range(5)]
    if any(n > 32 for n in counts):
        raise ValueError('Music catalog exceeds firmware limits')
    tracks = []
    for index in range(offset, min(offset+8, counts[GROUPS[group]])):
        identity = version + bytes([GROUPS[group]]) + index.to_bytes(2, 'big')
        item = request(controls, rail, Command.MUSIC_TRACK, identity, guard=guard)
        if len(item) < 8 or item[:7] != identity or not 1 <= item[7] <= 95 or len(item) != 8+item[7]:
            raise ValueError('Malformed or changed music track response')
        tracks.append(dict(group=group, index=index, filename=item[8:].decode('utf-8', errors='replace')))
    if request(controls, rail, Command.MUSIC_CATALOG, guard=guard) != data:
        raise ValueError('Catalog changed; refresh list')
    number = int.from_bytes(version, 'big')
    cached = previous['tracks'] if previous and previous['catalog_version'] == number else []
    cached = [t for t in cached if t['group'] != group or not offset <= t['index'] < offset+8]
    controls.music_catalogs[rail] = dict(catalog_version=number, tracks=cached+tracks)
    return dict(railing_id=rail, catalog_version=number, group=group, offset=offset,
                total=counts[GROUPS[group]], tracks=tracks)
