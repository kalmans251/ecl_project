from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import os

from audio import AudioManager
from device_control import DeviceControls, HELP as DEVICE_HELP, device_status
from emergency import EmergencyManager
from plc import PlcBus
from plc.events import EventPoller
from protocol import (
    AudioDirection,
    Command,
    Frame,
    Node,
    Service,
)
from railing import RailingManager
from voice import VoiceRelay


LOG = logging.getLogger("railing-pi")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Smart railing Raspberry Pi PLC controller"
    )

    parser.add_argument(
        "--port",
        default="/dev/serial0",
        help="PLC serial device (default: /dev/serial0)",
    )

    parser.add_argument(
        "--baud",
        type=int,
        default=9600,
        help="PLC baud rate (default: 9600)",
    )

    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=[
            "DEBUG",
            "INFO",
            "WARNING",
            "ERROR",
        ],
    )

    parser.add_argument(
        "--no-console",
        action="store_true",
        help="Run without the interactive command prompt",
    )

    parser.add_argument(
        "--voice-host",
        default="0.0.0.0",
        help="Codec2 relay TCP bind address (default: 0.0.0.0)",
    )

    parser.add_argument(
        "--voice-port",
        type=int,
        default=9100,
        help="Codec2 relay TCP port (default: 9100)",
    )

    parser.add_argument(
        "--disable-voice-relay",
        action="store_true",
        help="Do not start the control-center Codec2 TCP relay",
    )

    parser.add_argument('--local-audio', action='store_true',
                        help='Enable PTT-gated Pi USB microphone and AUX playback')
    parser.add_argument('--audio-railing', type=int, default=1)
    parser.add_argument('--mic-device', help='USB microphone index or name')
    parser.add_argument('--speaker-device', default='bcm2835 Headphones',
                        help='AUX output index/name (default: bcm2835 Headphones)')
    parser.add_argument('--list-audio-devices', action='store_true')
    parser.add_argument('--call-state-file', default=os.environ.get(
        'ECL_CALL_STATE_FILE', '~/.local/state/ecl-railing/calls.json'),
        help='Durable unresolved-call journal; keep the same path across restarts')
    parser.add_argument('--event-railings', default='1,2,3,4',
                        help='Comma-separated installed railing IDs to poll (default: 1,2,3,4)')
    parser.add_argument('--music-journal', default='~/.local/state/ecl-railing/music-requests.sqlite3', help='Durable remote music/general command journal; do not delete to retry a request')
    parser.add_argument('--music-sync', action='store_true', help='Poll actual music state round-robin')
    parser.add_argument('--music-poll-interval', type=float, default=2.0, help='Seconds between rails (1..30)')
    parser.add_argument('--web-voice', action='store_true', help='Enable WSS call/Codec2 bridge; excludes local audio and TCP voice listener')
    parser.add_argument('--monitor-url', help='Optional WSS gateway URL; enables music sync and confirmed remote controls')
    args = parser.parse_args()
    if not 1 <= args.music_poll_interval <= 30:
        parser.error('--music-poll-interval must be 1..30')
    if args.monitor_url:
        from music_sync import validate_url
        try:
            validate_url(args.monitor_url)
            if not os.environ.get('MONITOR_GATEWAY_TOKEN'):
                raise ValueError('Set MONITOR_GATEWAY_TOKEN')
        except ValueError as exc:
            parser.error(str(exc))
    try:
        args.event_railings = tuple(dict.fromkeys(int(x.strip(), 0) for x in args.event_railings.split(',')))
        if not args.event_railings or any(not 1 <= x <= 255 for x in args.event_railings):
            raise ValueError()
    except ValueError:
        parser.error('--event-railings requires IDs in 1..255')
    if not 1 <= args.audio_railing <= 255:
        parser.error('--audio-railing must be 1..255')
    return args


def print_help() -> None:
    print(
        "\nCommands:\n"
        + DEVICE_HELP +
        "  status [railing_id]  show cached railing state\n"
        "  ack <railing_id>     acknowledge active emergency\n"
        "  ping <railing_id>    send SYSTEM/PING to P4\n"
        "  call <id>           start a normal call (initial FIELD_TX)\n"
        "  ptt <id> on|off      switch CONTROL_TX / FIELD_TX\n"
        "  hangup <id>          end active call\n"
        "  music-sync-status  show background music snapshots\n"
        "  voice-status         show Codec2 relay counters\n"
        "  help                 show this help\n"
        "  quit                 exit\n"
    )


def main() -> int:
    args = parse_args()

    logging.basicConfig(
        level=getattr(
            logging,
            args.log_level,
        ),
        format=(
            "%(asctime)s %(levelname)s "
            "%(name)s: %(message)s"
        ),
    )

    if args.list_audio_devices:
        import sounddevice as sd
        print(sd.query_devices())
        return 0

    try:
        railings = RailingManager(state_file=args.call_state_file)
    except (OSError, ValueError):
        LOG.exception("Cannot load/save call recovery journal; refusing to start")
        return 1

    bus = PlcBus(
        port=args.port,
        baudrate=args.baud,
    )

    audio = AudioManager(bus, railings)
    emergency = EmergencyManager(bus, railings, audio=audio)

    voice = VoiceRelay(
        bus,
        railings,
        host=args.voice_host,
        port=args.voice_port,
    )

    if args.web_voice and (not args.monitor_url or args.local_audio):
        LOG.error('--web-voice requires --monitor-url and cannot be combined with --local-audio')
        return 1
    controls = DeviceControls(bus, railings, voice)
    local_audio = None
    radar_sync = None
    status_sync = None

    def on_frame(frame: Frame) -> None:
        if frame.railing_id == 0:
            LOG.warning(
                "Ignoring frame with railing_id=0"
            )
            return

        if int(frame.dst) != int(Node.PI):
            LOG.debug(
                "Ignoring frame not addressed to PI "
                "rail=%d src=%02X dst=%02X",
                frame.railing_id,
                int(frame.src),
                int(frame.dst),
            )
            return

        railings.mark_seen(
            frame.railing_id
        )

        if event_poller.handle_frame(frame):
            return

        if radar_sync and radar_sync.handle_frame(frame):
            return

        if controls.handle_frame(frame):
            return

        if emergency.handle_frame(frame):
            if status_sync: status_sync.emergency(frame.railing_id)
            voice.state_changed()
            return

        if audio.handle_frame(frame):
            voice.state_changed()
            return

        if voice.handle_plc_frame(frame):
            return

        status_message = device_status(frame)
        if status_message is not None:
            print("\n" + status_message)
            return

        LOG.info(
            "RX rail=%d src=%02X dst=%02X service=%02X "
            "cmd=%02X payload=%s",
            frame.railing_id,
            int(frame.src),
            int(frame.dst),
            int(frame.service),
            int(frame.command),
            frame.payload.hex(" "),
        )

    event_poller = EventPoller(bus, railings, audio, args.event_railings, on_frame)

    bus.set_frame_handler(
        on_frame
    )

    try:
        bus.open()
    except Exception:
        LOG.exception(
            "Failed to open PLC serial port"
        )
        return 1

    if not args.disable_voice_relay and not args.web_voice:
        try:
            voice.start()
        except Exception:
            bus.close()
            LOG.exception(
                "Failed to start voice relay"
            )
            return 1

    if args.local_audio:
        from voice.local_audio import LocalAudio
        local_audio = LocalAudio(voice, args.audio_railing, args.mic_device, args.speaker_device)
        try:
            local_audio.start()
        except Exception:
            voice.close()
            bus.close()
            LOG.exception('Failed to start local audio; check devices and requirements-playback.txt')
            return 1

    music_sync = publisher = None
    try:
        if args.music_sync or args.monitor_url:
            from music_sync import MusicSync, MusicPublisher
            if args.monitor_url:
                from music_remote import MusicRemote
                remote = MusicRemote(controls, args.event_railings, args.music_journal)
                calls = None
                if args.web_voice:
                    from call_remote import CallRemote
                    calls = CallRemote(audio, voice, railings, args.event_railings, remote.path, emergency=emergency)
                    voice.set_field_handler(calls.field)
                publisher = MusicPublisher(args.monitor_url, os.environ['MONITOR_GATEWAY_TOKEN'], remote, calls)
                from radar_sync import RadarSync
                radar_sync = RadarSync(bus, controls, audio, railings, args.event_railings, publisher.publish)
                publisher.radar = radar_sync
                publisher.start()
                radar_sync.start()
                from status_sync import StatusSync
                status_sync = StatusSync(controls, audio, args.event_railings, publisher)
                publisher.status = status_sync
                status_sync.start()
            music_sync = MusicSync(controls, args.event_railings, args.music_poll_interval,
                                   publisher.publish if publisher else None)
            music_sync.start()
    except Exception:
        if status_sync: status_sync.close()
        if radar_sync: radar_sync.close()
        if publisher: publisher.close()
        if local_audio: local_audio.close()
        voice.close(); bus.close()
        LOG.exception('Failed to start music sync')
        return 1

    audio.start_keepalive()
    event_poller.start()
    try:
        if args.no_console:
            while True:
                time.sleep(1.0)

        print_help()

        while True:
            try:
                line = input("railing> ").strip()
            except EOFError:
                break

            if not line:
                continue

            parts = line.split()
            command = parts[0].lower()

            if command in (
                "quit",
                "exit",
            ):
                break

            if command == "help":
                print_help()
                continue

            if command == "status":
                if len(parts) == 1:
                    snapshot = railings.snapshot()
                elif len(parts) == 2:
                    snapshot = railings.snapshot(
                        int(parts[1], 0)
                    )
                else:
                    print(
                        "usage: status [railing_id]"
                    )
                    continue

                print(
                    json.dumps(
                        snapshot,
                        indent=2,
                        ensure_ascii=False,
                    )
                )
                continue

            if command == "ack":
                if len(parts) != 2:
                    print(
                        "usage: ack <railing_id>"
                    )
                    continue

                railing_id = int(
                    parts[1],
                    0,
                )

                try:
                    seq = emergency.ack(
                        railing_id
                    )
                except Exception as exc:
                    print(
                        f"ACK failed: {exc}"
                    )
                    continue

                print(
                    f"ACK sent rail={railing_id} seq={seq}"
                )
                continue


            if args.web_voice and command in ("call", "ptt", "hangup", "ack"):
                print("Web voice owns call controls; use monitoring call/hangup buttons")
                continue
            if command == "call":
                if len(parts) != 2:
                    print("usage: call <railing_id>")
                    continue
                try:
                    railing_id = int(parts[1], 0)
                    started = audio.start_call(railing_id)
                except (ValueError, RuntimeError, OSError) as exc:
                    print(f"CALL failed: {exc}")
                    continue
                print(f"CALL {'confirmed' if started else 'already active'} rail={railing_id}; "
                      "use ptt on to talk, ptt off to listen")
                continue

            if command == "ptt":
                if (
                    len(parts) != 3
                    or parts[2].lower()
                    not in ("on", "off")
                ):
                    print(
                        "usage: ptt <railing_id> on|off"
                    )
                    continue

                railing_id = int(
                    parts[1],
                    0,
                )

                direction = (
                    AudioDirection.CONTROL_TX
                    if parts[2].lower() == "on"
                    else AudioDirection.FIELD_TX
                )

                try:
                    with voice.control_transition():
                        audio.set_direction(railing_id, direction)
                except Exception as exc:
                    print(
                        f"PTT failed: {exc}"
                    )
                    continue

                print(
                    f"PTT {'ON' if direction == AudioDirection.CONTROL_TX else 'OFF'} "
                    f"rail={railing_id}"
                )
                continue

            if command == "hangup":
                if len(parts) != 2:
                    print(
                        "usage: hangup <railing_id>"
                    )
                    continue

                railing_id = int(
                    parts[1],
                    0,
                )

                try:
                    with voice.control_transition():
                        ended = audio.end_call(railing_id)
                except Exception as exc:
                    print(
                        f"hangup failed: {exc}"
                    )
                    continue

                print(
                    f"CALL ended rail={railing_id}" if ended else
                    f"CALL locally idle rail={railing_id}; no remote confirmation requested"
                )
                continue

            if command == "music-sync-status":
                print(json.dumps(music_sync.snapshot() if music_sync else {}, indent=2, ensure_ascii=False))
                continue

            if command == "voice-status":
                print(
                    json.dumps(
                        {
                            "local_audio": local_audio.status() if local_audio else None,
                            "control_paused": voice.control_paused(),
                            "clients": voice.client_count(),
                            "field_packets": voice.field_packets,
                            "control_packets": voice.control_packets,
                            "dropped_packets": voice.dropped_packets,
                            "network_dropped_packets": voice.network_dropped_packets,
                            "listen": (
                                None
                                if args.disable_voice_relay
                                else f"{args.voice_host}:{args.voice_port}"
                            ),
                        },
                        indent=2,
                    )
                )
                continue

            try:
                result = controls.execute(parts)
            except (ValueError, RuntimeError, OSError) as exc:
                print(f"Control failed: {exc}")
                continue
            if result is not None:
                print(result)
                continue

            print(
                f"unknown command: {command}"
            )

    except KeyboardInterrupt:
        print()

    finally:
        if music_sync: music_sync.close()
        if status_sync: status_sync.close()
        if radar_sync: radar_sync.close()
        if publisher: publisher.close()
        event_poller.close()
        audio.close()
        if local_audio:
            local_audio.close()
        voice.close()
        bus.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
