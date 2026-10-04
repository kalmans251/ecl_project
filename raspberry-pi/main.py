from __future__ import annotations

import argparse
import json
import logging
import sys
import time

from emergency import EmergencyManager
from plc import PlcBus
from protocol import Command, Frame, Node, Service
from railing import RailingManager


LOG = logging.getLogger("railing-pi")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Smart railing Raspberry Pi PLC controller"
    )

    parser.add_argument(
        "--port",
        default="/dev/ttyAMA2",
        help="PLC serial device (default: /dev/ttyAMA2)",
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

    return parser.parse_args()


def print_help() -> None:
    print(
        "\nCommands:\n"
        "  status [railing_id]  show cached railing state\n"
        "  ack <railing_id>     acknowledge active emergency\n"
        "  ping <railing_id>    send SYSTEM/PING to P4\n"
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

    railings = RailingManager()

    bus = PlcBus(
        port=args.port,
        baudrate=args.baud,
    )

    emergency = EmergencyManager(
        bus,
        railings,
    )

    def on_frame(frame: Frame) -> None:
        if frame.railing_id == 0:
            LOG.warning(
                "Ignoring frame with railing_id=0"
            )
            return

        railings.mark_seen(
            frame.railing_id
        )

        if emergency.handle_frame(frame):
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

            if command == "ping":
                if len(parts) != 2:
                    print(
                        "usage: ping <railing_id>"
                    )
                    continue

                railing_id = int(
                    parts[1],
                    0,
                )

                bus.send_frame(
                    Frame(
                        railing_id=railing_id,
                        src=Node.PI,
                        dst=Node.P4,
                        service=Service.SYSTEM,
                        command=Command.PING,
                    )
                )

                print(
                    f"PING sent rail={railing_id}"
                )
                continue

            print(
                f"unknown command: {command}"
            )

    except KeyboardInterrupt:
        print()

    finally:
        bus.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
