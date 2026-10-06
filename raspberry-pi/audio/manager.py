from __future__ import annotations

import logging
import threading
import time

from plc import PlcBus
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
        bus: PlcBus,
        railings: RailingManager,
        *,
        ack_timeout: float = 0.5,
        attempts: int = 3,
    ) -> None:
        self._bus = bus
        self._railings = railings
        self._ack_timeout = ack_timeout
        self._attempts = attempts
        self._condition = threading.Condition()
        self._control_lock = threading.Lock()
        self._direction_revision: dict[int, int] = {}
        self._start_revision: dict[int, int] = {}

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
            if (origin not in (int(CallOrigin.NORMAL), int(CallOrigin.EMERGENCY))
                    or direction not in (int(AudioDirection.FIELD_TX), int(AudioDirection.CONTROL_TX))):
                LOG.warning("Invalid CALL STARTED event rail=%d", frame.railing_id)
                return True
            self._railings.call_started(
                frame.railing_id,
                origin,
                direction,
            )

            with self._condition:
                self._start_revision[frame.railing_id] = (
                    self._start_revision.get(frame.railing_id, 0) + 1)
                self._condition.notify_all()

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

            with self._condition:
                self._direction_revision[frame.railing_id] = (
                    self._direction_revision.get(frame.railing_id, 0) + 1)
                self._condition.notify_all()

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
            with self._condition:
                self._condition.notify_all()

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


    def start_call(self, railing_id: int) -> bool:
        """Start a normal call; return False if this railing is already connected.

        Keep local audio disabled until the P4 CALL_STARTED event. This method
        runs on the control thread, never from the PLC reader callback.
        """
        if not 1 <= railing_id <= 255:
            raise ValueError("railing_id must be 1..255")
        frame = Frame(railing_id=railing_id, src=Node.PI, dst=Node.P4,
                      service=Service.AUDIO, command=Command.START)
        with self._control_lock:
            if self._railings.get_call_direction(railing_id) is not None:
                return False
            for state in self._railings.snapshot().values():
                if state["emergency"]["active"]:
                    raise RuntimeError("An emergency is active; use ack for the emergency call")
                if state["call"]["active"]:
                    raise RuntimeError("Another railing has an active call; hang up first")
            with self._condition:
                revision = self._start_revision.get(railing_id, 0)
            for attempt in range(1, self._attempts + 1):
                # A late confirmation from the previous attempt may already be here.
                with self._condition:
                    if self._start_revision.get(railing_id, 0) > revision:
                        if self._railings.get_call_direction(railing_id) is None:
                            raise RuntimeError("Call ended before start confirmation")
                        return True
                LOG.info("CALL start request rail=%d attempt=%d/%d",
                         railing_id, attempt, self._attempts)
                try:
                    # Idle P4 also grants receive windows. Use them rather than
                    # racing a P4 transmission or an unknown field voice stream.
                    self._bus.send_control_frame(frame, wait_for_window=True)
                except TimeoutError:
                    if attempt == self._attempts:
                        raise
                    continue
                deadline = time.monotonic() + self._ack_timeout
                with self._condition:
                    while self._start_revision.get(railing_id, 0) <= revision:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            break
                        self._condition.wait(remaining)
                    if self._start_revision.get(railing_id, 0) > revision:
                        if self._railings.get_call_direction(railing_id) is None:
                            raise RuntimeError("Call ended before start confirmation")
                        LOG.info("CALL start confirmed rail=%d", railing_id)
                        return True
                LOG.warning("No P4 call-start confirmation rail=%d attempt=%d", railing_id, attempt)
            raise TimeoutError("Call start was not confirmed by P4; the remote call may have started")

    def set_direction(
        self,
        railing_id: int,
        direction: AudioDirection,
    ) -> None:
        if direction not in (
            AudioDirection.FIELD_TX,
            AudioDirection.CONTROL_TX,
        ):
            raise ValueError(
                f"invalid audio direction: {direction}"
            )

        frame = Frame(
                railing_id=railing_id,
                src=Node.PI,
                dst=Node.P4,
                service=Service.AUDIO,
                command=Command.SET,
                payload=bytes(
                    [
                        int(direction)
                    ]
                ),
        )
        with self._control_lock:
            for attempt in range(1, self._attempts + 1):
                current = self._railings.get_call_direction(railing_id)
                if current is None:
                    raise RuntimeError("No confirmed active call for this railing")
                with self._condition:
                    revision = self._direction_revision.get(railing_id, 0)
                LOG.info("CALL direction request rail=%d direction=%s attempt=%d/%d",
                         railing_id, self._direction_name(int(direction)),
                         attempt, self._attempts)
                try:
                    self._bus.send_control_frame(
                        frame, wait_for_window=(current == int(AudioDirection.FIELD_TX)))
                except TimeoutError:
                    if attempt == self._attempts:
                        raise
                    continue
                deadline = time.monotonic() + self._ack_timeout
                with self._condition:
                    while True:
                        confirmed = self._railings.get_call_direction(railing_id)
                        if confirmed is None:
                            raise RuntimeError("Call ended before PTT confirmation")
                        if (self._direction_revision.get(railing_id, 0) > revision
                                and confirmed == int(direction)):
                            LOG.info("PTT confirmed rail=%d direction=%s", railing_id,
                                     self._direction_name(int(direction)))
                            return
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            break
                        self._condition.wait(remaining)
                LOG.warning("No P4 direction confirmation rail=%d attempt=%d",
                            railing_id, attempt)
            raise TimeoutError("PTT direction was not confirmed by P4")

    def end_call(
        self,
        railing_id: int,
    ) -> None:
        with self._control_lock:
            for attempt in range(1, self._attempts + 1):
                current = self._railings.get_call_direction(railing_id)
                if current is None:
                    return
                try:
                    self._bus.send_control_frame(
                        Frame(railing_id=railing_id, src=Node.PI, dst=Node.P4,
                              service=Service.AUDIO, command=Command.STOP),
                        wait_for_window=(current == int(AudioDirection.FIELD_TX)))
                except TimeoutError:
                    if attempt == self._attempts:
                        raise
                    continue
                deadline = time.monotonic() + self._ack_timeout
                with self._condition:
                    while self._railings.get_call_direction(railing_id) is not None:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            break
                        self._condition.wait(remaining)
                    if self._railings.get_call_direction(railing_id) is None:
                        LOG.info("CALL end confirmed rail=%d", railing_id)
                        return
                LOG.warning("No P4 hangup confirmation rail=%d attempt=%d", railing_id, attempt)
            raise TimeoutError("Hangup was not confirmed by P4")

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
