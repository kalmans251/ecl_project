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
        recovery_grace_seconds: float = 12.0,
    ) -> None:
        self._recovery_baseline = time.monotonic()
        self._recovery_grace = recovery_grace_seconds
        self._bus = bus
        self._railings = railings
        self._ack_timeout = ack_timeout
        self._attempts = attempts
        self._condition = threading.Condition()
        self._control_lock = threading.Lock()
        self._direction_revision: dict[int, int] = {}
        self._start_revision: dict[int, int] = {}
        self._keepalive_due = threading.Event()
        self._keepalive_stop = threading.Event()
        self._keepalive_thread = None

    def session_bytes(self, rail):
        return self._railings.snapshot(rail).get("call", {}).get("session_id", 0).to_bytes(4, "big")

    def recovery_delay(self, rail):
        call=self._railings.snapshot(rail).get("call", {})
        latest=max(self._recovery_baseline, call.get("started_monotonic") or 0.0,
                   getattr(self._bus, "last_call_tx", lambda rid: 0.0)(rail))
        return max(0.0, latest + self._recovery_grace - time.monotonic())

    def start_keepalive(self) -> None:
        if self._keepalive_thread is not None:
            return
        self._keepalive_stop.clear()
        self._keepalive_thread = threading.Thread(target=self._keepalive_loop,
            name="call-keepalive", daemon=True)
        self._keepalive_thread.start()

    def close(self) -> None:
        self._keepalive_stop.set()
        if self._keepalive_thread is not None:
            self._keepalive_thread.join(timeout=2.0)
            self._keepalive_thread = None

    def _keepalive_loop(self) -> None:
        while not self._keepalive_stop.wait(1.0):
            try:
                self.renew_calls()
            except Exception:
                LOG.exception("Call keepalive failed; P4 lease may expire")

    def renew_calls(self) -> None:
        # Yield to explicit PTT/hangup; never renew recovered/unknown calls.
        self._keepalive_due.set()
        if not self._control_lock.acquire(blocking=False):
            return
        try:
            for rid, state in self._railings.snapshot().items():
                call = state["call"]
                if call["phase"] != "active" or not call["active"]:
                    continue
                self._bus.send_control_frame(
                    Frame(rid, Node.PI, Node.P4, Service.AUDIO, Command.CALL_KEEPALIVE, self.session_bytes(rid)),
                    wait_for_window=call["direction"] == int(AudioDirection.FIELD_TX),
                    timeout=0.8)
            self._keepalive_due.clear()
        finally:
            self._control_lock.release()

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

        if (len(frame.payload) != 8 or not self._railings.call_pending(frame.railing_id)
                or frame.payload[4:8] != self.session_bytes(frame.railing_id)):
            LOG.warning("Ignoring stale/unmatched call event rail=%d", frame.railing_id)
            return True

        session_id = int.from_bytes(frame.payload[4:8], "big")
        event = frame.payload[1]
        origin = frame.payload[2]
        direction = frame.payload[3]

        if event == int(AudioEvent.CALL_STARTED):
            if (origin not in (int(CallOrigin.NORMAL), int(CallOrigin.EMERGENCY))
                    or direction not in (int(AudioDirection.FIELD_TX), int(AudioDirection.CONTROL_TX))):
                LOG.warning("Invalid CALL STARTED event rail=%d", frame.railing_id)
                return True
            if not self._railings.call_started(frame.railing_id, origin, direction, session_id=session_id):
                LOG.warning("Recovered call rail=%d requires confirmed hangup; ignoring late START", frame.railing_id)
                return True

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
                    direction, session_id=session_id,
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
            if not self._railings.call_ended(frame.railing_id, session_id=session_id):
                return True
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
        if not 1 <= railing_id <= 255:
            raise ValueError("railing_id must be 1..255")
        if self._railings.get_call_direction(railing_id) is not None:
            if self._railings.snapshot(railing_id)["call"]["phase"] != "active":
                raise RuntimeError("Call unresolved; hangup first")
            return False
        self._railings.reserve_call(railing_id)
        try:
            return self._start_call(railing_id)
        except Exception:
            self._railings.call_request_failed(railing_id)
            raise

    def _start_call(self, railing_id: int) -> bool:
        """Start a normal call; return False if this railing is already connected.

        Keep local audio disabled until the P4 CALL_STARTED event. This method
        runs on the control thread, never from the PLC reader callback.
        """
        if not 1 <= railing_id <= 255:
            raise ValueError("railing_id must be 1..255")
        frame = Frame(railing_id=railing_id, src=Node.PI, dst=Node.P4,
                      service=Service.AUDIO, command=Command.START, payload=self.session_bytes(railing_id))
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
                    # P4 emits receive grants only during FIELD_TX calls. A
                    # normal call starts from idle, so use the existing guarded
                    # direct-control path; waiting for a grant would deadlock.
                    self._bus.send_control_frame(frame, wait_for_window=False)
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
                ) + self.session_bytes(railing_id),
        )
        with self._control_lock:
            if self._railings.snapshot(railing_id).get("call", {}).get("phase") != "active":
                raise RuntimeError("No confirmed active call; hangup unresolved call first")
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

    def end_call(self, railing_id: int) -> bool:
        """Return True only after remote END; False means locally idle/no request."""
        if not 1 <= railing_id <= 255:
            raise ValueError("railing_id must be 1..255")
        with self._control_lock:
            if not self._railings.call_pending(railing_id):
                return False
            current = self._railings.get_call_direction(railing_id)
            uncertain = current is None
            self._railings.call_end_requested(railing_id)
            try:
                for attempt in range(1, self._attempts + 1):
                    if not self._railings.call_pending(railing_id):
                        return True
                    frame = Frame(railing_id, Node.PI, Node.P4, Service.AUDIO, Command.STOP, self.session_bytes(railing_id))
                    try:
                        self._bus.send_control_frame(frame, wait_for_window=(
                            uncertain or current == int(AudioDirection.FIELD_TX)))
                    except TimeoutError:
                        if not self._railings.call_pending(railing_id):
                            return True
                        # No idle grants: wait beyond the last possible P4 lease
                        # before probing directly. Elapsed time never confirms END.
                        with self._condition:
                            while self._railings.call_pending(railing_id) and self.recovery_delay(railing_id)>0:
                                self._condition.wait(min(0.1,self.recovery_delay(railing_id)))
                        if not self._railings.call_pending(railing_id):
                            return True
                        self._bus.send_control_frame(frame, wait_for_window=False)
                    deadline = time.monotonic() + self._ack_timeout * 3
                    with self._condition:
                        while self._railings.call_pending(railing_id):
                            remaining = deadline - time.monotonic()
                            if remaining <= 0:
                                break
                            self._condition.wait(remaining)
                    if not self._railings.call_pending(railing_id):
                        LOG.info("CALL end confirmed rail=%d", railing_id)
                        return True
                    LOG.warning("No P4 hangup confirmation rail=%d attempt=%d", railing_id, attempt)
                raise TimeoutError("Hangup was not confirmed by P4; state remains unknown")
            except Exception:
                self._railings.call_request_failed(railing_id)
                raise

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
