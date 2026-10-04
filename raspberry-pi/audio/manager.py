from __future__ import annotations

import logging

from protocol import (
    AudioDataType,
    AudioDirection,
    AudioEvent,
    CallOrigin,
    Command,
    Frame,
    Node,
    Service,
)
from railing import RailingManager


LOG = logging.getLogger(__name__)


class AudioManager:
    def __init__(
        self,
        railings: RailingManager,
    ) -> None:
        self._railings = railings

    def handle_frame(
        self,
        frame: Frame,
    ) -> bool:
        if (
            int(frame.service) != int(Service.AUDIO)
            or int(frame.dst) != int(Node.PI)
            or int(frame.src) != int(Node.P4)
            or int(frame.command) != int(Command.DATA)
        ):
            return False

        if len(frame.payload) < 1:
            LOG.warning(
                "AUDIO DATA payload empty rail=%d",
                frame.railing_id,
            )
            return True

        data_type = frame.payload[0]

        if data_type != int(AudioDataType.EVENT):
            return False

        if len(frame.payload) < 4:
            LOG.warning(
                "AUDIO EVENT payload too short rail=%d len=%d",
                frame.railing_id,
                len(frame.payload),
            )
            return True

        event = frame.payload[1]
        origin = frame.payload[2]
        direction = frame.payload[3]

        if event == int(AudioEvent.CALL_STARTED):
            self._railings.call_started(
                frame.railing_id,
                origin,
                direction,
            )

            LOG.info(
                "CALL STARTED rail=%d origin=%s direction=%s",
                frame.railing_id,
                self._origin_name(origin),
                self._direction_name(direction),
            )

            print(
                f"\n[CALL] STARTED "
                f"rail={frame.railing_id} "
                f"origin={self._origin_name(origin)} "
                f"direction={self._direction_name(direction)}"
            )

            return True

        if event == int(AudioEvent.DIRECTION_CHANGED):
            updated = (
                self._railings.call_direction_changed(
                    frame.railing_id,
                    direction,
                )
            )

            if not updated:
                LOG.warning(
                    "CALL direction event without active call "
                    "rail=%d direction=%s",
                    frame.railing_id,
                    self._direction_name(direction),
                )
                return True

            LOG.info(
                "CALL DIRECTION rail=%d direction=%s",
                frame.railing_id,
                self._direction_name(direction),
            )

            print(
                f"\n[CALL] DIRECTION "
                f"rail={frame.railing_id} "
                f"{self._direction_name(direction)}"
            )

            return True

        if event == int(AudioEvent.CALL_ENDED):
            self._railings.call_ended(
                frame.railing_id
            )

            LOG.info(
                "CALL ENDED rail=%d origin=%s",
                frame.railing_id,
                self._origin_name(origin),
            )

            print(
                f"\n[CALL] ENDED "
                f"rail={frame.railing_id} "
                f"origin={self._origin_name(origin)}"
            )

            return True

        LOG.warning(
            "Unknown AUDIO EVENT rail=%d event=0x%02X",
            frame.railing_id,
            event,
        )

        return True

    @staticmethod
    def _direction_name(
        direction: int,
    ) -> str:
        if direction == int(
            AudioDirection.FIELD_TX
        ):
            return "FIELD_TX"

        if direction == int(
            AudioDirection.CONTROL_TX
        ):
            return "CONTROL_TX"

        return f"0x{direction:02X}"

    @staticmethod
    def _origin_name(
        origin: int,
    ) -> str:
        if origin == int(
            CallOrigin.NORMAL
        ):
            return "NORMAL"

        if origin == int(
            CallOrigin.EMERGENCY
        ):
            return "EMERGENCY"

        return f"0x{origin:02X}"
