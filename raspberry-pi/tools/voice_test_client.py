from __future__ import annotations

import argparse
from pathlib import Path
import socket
import sys
import threading
import time


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(ROOT),
    )


from protocol import (  # noqa: E402
    AudioDirection,
    Codec2Mode,
)
from voice import (  # noqa: E402
    VoicePacket,
    VoiceStreamParser,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Test the Raspberry Pi Codec2 packet relay. "
            "This sends dummy 6-byte Codec2 frames; "
            "it does not encode or decode audio."
        )
    )

    parser.add_argument(
        "host",
        help="Raspberry Pi IP address",
    )

    parser.add_argument(
        "--port",
        type=int,
        default=9100,
    )

    parser.add_argument(
        "--railing",
        type=int,
        default=1,
    )

    parser.add_argument(
        "--send-control",
        action="store_true",
        help=(
            "Send dummy CONTROL_TX packets. "
            "Run 'ptt <id> on' on the Pi first."
        ),
    )

    parser.add_argument(
        "--count",
        type=int,
        default=10,
    )

    parser.add_argument(
        "--interval",
        type=float,
        default=0.16,
        help="Seconds between dummy packets",
    )

    return parser.parse_args()


def receive_loop(
    sock: socket.socket,
) -> None:
    parser = VoiceStreamParser()

    while True:
        try:
            data = sock.recv(
                4096
            )
        except OSError:
            return

        if not data:
            return

        for packet in parser.feed(
            data
        ):
            print(
                "FIELD RX "
                f"rail={packet.railing_id} "
                f"seq={packet.sequence} "
                f"frames={packet.frame_count} "
                f"bytes={len(packet.data)}"
            )


def main() -> int:
    args = parse_args()

    sock = socket.create_connection(
        (
            args.host,
            args.port,
        ),
        timeout=5.0,
    )

    print(
        f"Connected to "
        f"{args.host}:{args.port}"
    )

    threading.Thread(
        target=receive_loop,
        args=(sock,),
        daemon=True,
    ).start()

    if args.send_control:
        for sequence in range(
            args.count
        ):
            data = bytes(
                (
                    (
                        sequence
                        +
                        index
                    )
                    &
                    0xFF
                )
                for index in range(48)
            )

            packet = VoicePacket(
                railing_id=args.railing,
                direction=int(
                    AudioDirection.CONTROL_TX
                ),
                mode=int(
                    Codec2Mode.MODE_2400
                ),
                sequence=sequence,
                frame_count=8,
                bytes_per_frame=6,
                data=data,
            )

            sock.sendall(
                packet.encode_network()
            )

            print(
                "CONTROL TX "
                f"rail={args.railing} "
                f"seq={sequence} "
                "frames=8 bytes=48"
            )

            time.sleep(
                args.interval
            )

        time.sleep(
            1.0
        )

        sock.close()
        return 0

    try:
        while True:
            time.sleep(
                1.0
            )
    except KeyboardInterrupt:
        pass
    finally:
        sock.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
