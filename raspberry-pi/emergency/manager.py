from __future__ import annotations

import logging

from plc import PlcBus
from protocol import (
    Command,
    EmergencyAction,
    EmergencyEvent,
    EmergencySource,
    Frame,
    Node,
    Service,
)
from protocol.frame import read_u32_be, write_u32_be
from railing import RailingManager


LOG = logging.getLogger(__name__)


class EmergencyManager:
    def __init__(
        self,
        bus: PlcBus,
        railings: RailingManager,
    ) -> None:
        self._bus = bus
        self._railings = railings

    def handle_frame(
        self,
        frame: Frame,
    ) -> bool:
        if (
            int(frame.service) != int(Service.EMERGENCY)
            or int(frame.dst) != int(Node.PI)
            or int(frame.src) != int(Node.P4)
        ):
            return False

        if frame.command == int(Command.DATA):
            if (
                len(frame.payload) >= 5
                and frame.payload[0]
                == int(EmergencyEvent.ACKED)
            ):
                seq = read_u32_be(
                    frame.payload[1:5]
                )

                matched = (
                    self._railings.emergency_ack_confirmed(
                        frame.railing_id,
                        seq,
                    )
                )

                if not matched:
                    LOG.warning(
                        "Ignoring emergency ACKED with mismatched seq "
                        "rail=%d seq=%d",
                        frame.railing_id,
                        seq,
                    )
                    return True

                LOG.info(
                    "EMERGENCY ACK CONFIRMED rail=%d seq=%d",
                    frame.railing_id,
                    seq,
                )

                print(
                    f"\n[EMERGENCY] ACK CONFIRMED "
                    f"rail={frame.railing_id} "
                    f"seq={seq}"
                )

                return True

            return False

        if frame.command not in (
            int(Command.START),
            int(Command.STOP),
        ):
            return False

        if len(frame.payload) < 5:
            LOG.warning(
                "Emergency frame too short rail=%d cmd=0x%02X len=%d",
                frame.railing_id,
                int(frame.command),
                len(frame.payload),
            )
            return True

        source = frame.payload[0]
        seq = read_u32_be(
            frame.payload[1:5]
        )

        if frame.command == int(Command.START):
            self._railings.emergency_start(
                frame.railing_id,
                source,
                seq,
            )

            LOG.warning(
                "EMERGENCY START rail=%d source=%s seq=%d",
                frame.railing_id,
                self._source_name(source),
                seq,
            )

            print(
                f"\n[EMERGENCY] START "
                f"rail={frame.railing_id} "
                f"source={self._source_name(source)} "
                f"seq={seq}"
            )

            return True

        matched = self._railings.emergency_stop(
            frame.railing_id,
            seq,
        )

        if not matched:
            LOG.warning(
                "Ignoring emergency STOP with mismatched seq "
                "rail=%d seq=%d",
                frame.railing_id,
                seq,
            )
            return True

        LOG.info(
            "EMERGENCY STOP rail=%d seq=%d",
            frame.railing_id,
            seq,
        )

        print(
            f"\n[EMERGENCY] STOP "
            f"rail={frame.railing_id} "
            f"seq={seq}"
        )

        return True

    def ack(
        self,
        railing_id: int,
    ) -> int:
        active = self._railings.get_active_emergency(
            railing_id
        )

        if active is None:
            raise RuntimeError(
                f"railing {railing_id}: no active emergency"
            )

        _, seq = active

        payload = (
            bytes(
                [
                    int(EmergencyAction.ACK)
                ]
            )
            + write_u32_be(seq)
        )

        frame = Frame(
            railing_id=railing_id,
            src=Node.PI,
            dst=Node.P4,
            service=Service.EMERGENCY,
            command=Command.SET,
            payload=payload,
        )

        self._bus.send_frame(frame)

        self._railings.mark_emergency_ack_sent(
            railing_id,
            seq,
        )

        LOG.info(
            "Emergency ACK sent rail=%d seq=%d",
            railing_id,
            seq,
        )

        return seq

    @staticmethod
    def _source_name(source: int) -> str:
        if source == int(EmergencySource.BUTTON):
            return "BUTTON"

        return f"0x{source:02X}"
