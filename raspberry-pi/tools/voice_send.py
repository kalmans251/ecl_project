"""Local Pi microphone or test tone -> existing voice relay -> WROOM."""
from __future__ import annotations
import argparse
from array import array
import math
from pathlib import Path
import queue
import socket
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from protocol import AudioDirection, Codec2Mode
from voice import VoicePacket
from voice.playback import Codec2Encoder


from voice.local_audio import downsample

def main():
    parser = argparse.ArgumentParser(description='Pi mic/test tone -> WROOM speaker (requires confirmed PTT ON)')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=9100)
    parser.add_argument('--railing', type=int, default=1)
    parser.add_argument('--device', help='input device number/name')
    parser.add_argument('--list-devices', action='store_true')
    parser.add_argument('--rate', type=int, choices=[8000, 16000, 48000], default=48000)
    parser.add_argument('--tone', action='store_true', help='send 440Hz tone without microphone')
    parser.add_argument('--seconds', type=float, default=0, help='duration; 0 = until Ctrl+C')
    args = parser.parse_args()
    if not 1 <= args.railing <= 255 or args.seconds < 0:
        parser.error('railing must be 1..255 and seconds must be >= 0')
    sd = None
    if not args.tone or args.list_devices:
        try:
            import sounddevice as sd
        except ImportError:
            parser.error('pip install -r requirements-playback.txt')
    if args.list_devices:
        print(sd.query_devices())
        return
    device = int(args.device) if args.device and args.device.isdecimal() else args.device
    capture = queue.Queue(maxsize=24)
    dropped = input_overflows = 0
    def callback(indata, frames, time_info, status):
        nonlocal dropped, input_overflows
        if status.input_overflow:
            input_overflows += 1
        try:
            capture.put_nowait(bytes(indata))
        except queue.Full:
            dropped += 1
    encoder = Codec2Encoder()
    stream = None
    packets = sequence = sample_index = 0
    try:
        if not args.tone:
            sd.check_input_settings(device=device, channels=1, dtype='int16', samplerate=args.rate)
            stream = sd.RawInputStream(device=device, samplerate=args.rate, channels=1,
                                      dtype='int16', blocksize=args.rate//50, callback=callback)
            stream.start()
        with socket.create_connection((args.host, args.port), timeout=5) as sock:
            started = time.monotonic()
            next_tone = started
            next_report = started + 5
            encoded = bytearray()
            print('Sending CONTROL_TX. Confirm ptt on in main.py first. Ctrl+C stops capture, not PTT.')
            while not args.seconds or time.monotonic() - started < args.seconds:
                if args.tone:
                    wait = next_tone - time.monotonic()
                    if wait > 0:
                        time.sleep(wait)
                    next_tone += 0.02
                    pcm = array('h', (int(3000 * math.sin(2*math.pi*440*(sample_index+i)/8000))
                                      for i in range(160))).tobytes()
                    sample_index += 160
                else:
                    try:
                        pcm = downsample(capture.get(timeout=1), args.rate)
                    except queue.Empty:
                        raise RuntimeError('No microphone samples received')
                encoded.extend(encoder.encode(pcm))
                if len(encoded) == 48:
                    packet = VoicePacket(args.railing, int(AudioDirection.CONTROL_TX),
                                         int(Codec2Mode.MODE_2400), sequence, 8, 6, bytes(encoded))
                    sock.sendall(packet.encode_network())
                    encoded.clear()
                    packets += 1
                    sequence = (sequence + 1) & 0xffff
                if time.monotonic() >= next_report:
                    print(dict(sent_packets=packets, capture_dropped_frames=dropped,
                               device_input_overflows=input_overflows, capture_queue=capture.qsize()), flush=True)
                    next_report = time.monotonic() + 5
    finally:
        if stream:
            stream.stop()
            stream.close()
        encoder.close()
        print('Final:', dict(sent_packets=packets, capture_dropped_frames=dropped,
                              device_input_overflows=input_overflows))


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        print(f'Voice send failed: {exc}', file=sys.stderr)
        sys.exit(1)
