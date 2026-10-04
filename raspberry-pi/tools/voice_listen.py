"""Listen on the Pi itself through its existing localhost voice relay."""
from __future__ import annotations
import argparse
from pathlib import Path
import socket
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from protocol import AudioDirection
from voice import VoiceStreamParser
from voice.playback import Codec2Decoder, PlaybackBuffer, upsample


def main():
    parser = argparse.ArgumentParser(description='Local Pi FIELD Codec2 playback; no PC server required')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=9100)
    parser.add_argument('--railing', type=int, default=1)
    parser.add_argument('--device', help='sounddevice output index or name')
    parser.add_argument('--list-devices', action='store_true')
    parser.add_argument('--buffer-ms', type=int, default=600)
    parser.add_argument('--rate', type=int, choices=[8000, 16000, 48000], default=48000)
    args = parser.parse_args()
    try:
        import sounddevice as sd
    except ImportError:
        parser.error('Install playback dependencies: pip install -r requirements-playback.txt')
    if args.list_devices:
        print(sd.query_devices())
        return
    device = int(args.device) if args.device and args.device.isdecimal() else args.device
    buffer = PlaybackBuffer(args.rate, args.buffer_ms)
    decoder = Codec2Decoder()
    stream_parser = VoiceStreamParser()
    packets = missing = stale = resets = 0
    previous = None
    last_packet = None
    next_report = time.monotonic() + 5
    try:
        sd.check_output_settings(device=device, channels=1, dtype='int16', samplerate=args.rate)
        with socket.create_connection((args.host, args.port), timeout=5) as sock:
            sock.settimeout(0.5)
            with sd.RawOutputStream(device=device, samplerate=args.rate, channels=1,
                                    dtype='int16', blocksize=args.rate // 50,
                                    callback=buffer.callback):
                print(f'Listening rail={args.railing}; buffer={args.buffer_ms}ms. Keep FIELD_TX (ptt off). Ctrl+C stops.')
                while True:
                    try:
                        data = sock.recv(4096)
                        if not data:
                            raise RuntimeError('Pi voice relay disconnected')
                    except socket.timeout:
                        data = b''
                    for packet in stream_parser.feed(data):
                        if packet.railing_id != args.railing or packet.direction != int(AudioDirection.FIELD_TX):
                            continue
                        now = time.monotonic()
                        if last_packet is not None and now - last_packet > 1:
                            buffer.clear()
                            decoder.close()
                            decoder = Codec2Decoder()
                            previous = None
                            resets += 1
                        if previous is not None:
                            delta = (packet.sequence - previous) & 0xffff
                            if delta == 0 or delta >= 0x8000:
                                stale += 1
                                continue
                            if delta > 1:
                                missing += delta - 1
                                # Bound concealment; a restart/large gap must not create huge silence.
                                if delta <= 11:
                                    buffer.push(bytes((delta - 1) * packet.frame_count * 160 * 2 * (args.rate // 8000)))
                                else:
                                    buffer.clear()
                                    decoder.close()
                                    decoder = Codec2Decoder()
                                    resets += 1
                        previous = packet.sequence
                        last_packet = now
                        packets += 1
                        buffer.push(upsample(decoder.decode(packet.data), args.rate // 8000))
                    if time.monotonic() >= next_report:
                        print(dict(packets=packets, missing_packets=missing, stale_packets=stale,
                                   resets=resets, **buffer.status()), flush=True)
                        next_report = time.monotonic() + 5
    finally:
        decoder.close()
        print('Final:', dict(packets=packets, missing_packets=missing, stale_packets=stale,
                              resets=resets, **buffer.status()))


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        print(f'Playback failed: {exc}', file=sys.stderr)
        sys.exit(1)
