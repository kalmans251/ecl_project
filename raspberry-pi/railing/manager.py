from __future__ import annotations

import threading
from dataclasses import asdict

from .state import RailingState


class RailingManager:
    def __init__(self) -> None:
        self._states: dict[int, RailingState] = {}
        self._lock = threading.RLock()

    def _get_or_create_locked(
        self,
        railing_id: int,
    ) -> RailingState:
        state = self._states.get(railing_id)

        if state is None:
            state = RailingState(
                railing_id=railing_id
            )
            self._states[railing_id] = state

        return state

    def mark_seen(
        self,
        railing_id: int,
    ) -> None:
        with self._lock:
            state = self._get_or_create_locked(
                railing_id
            )
            state.mark_seen()

    def emergency_start(
        self,
        railing_id: int,
        source: int,
        seq: int,
    ) -> None:
        with self._lock:
            state = self._get_or_create_locked(
                railing_id
            )
            state.mark_seen()

            state.emergency.active = True
            state.emergency.source = source
            state.emergency.seq = seq
            state.emergency.ack_sent = False

            from time import monotonic

            state.emergency.started_monotonic = (
                monotonic()
            )

    def emergency_stop(
        self,
        railing_id: int,
        seq: int,
    ) -> bool:
        with self._lock:
            state = self._get_or_create_locked(
                railing_id
            )
            state.mark_seen()

            current_seq = state.emergency.seq

            if (
                state.emergency.active
                and current_seq is not None
                and current_seq != seq
            ):
                return False

            state.emergency.active = False
            state.emergency.seq = None
            state.emergency.source = None
            state.emergency.ack_sent = False
            state.emergency.started_monotonic = None

            return True

    def mark_emergency_ack_sent(
        self,
        railing_id: int,
        seq: int,
    ) -> bool:
        with self._lock:
            state = self._states.get(
                railing_id
            )

            if (
                state is None
                or not state.emergency.active
                or state.emergency.seq != seq
            ):
                return False

            state.emergency.ack_sent = True
            return True

    def emergency_ack_confirmed(
        self,
        railing_id: int,
        seq: int,
    ) -> bool:
        with self._lock:
            state = self._states.get(
                railing_id
            )

            if (
                state is None
                or not state.emergency.active
                or state.emergency.seq != seq
            ):
                return False

            state.emergency.active = False
            state.emergency.seq = None
            state.emergency.source = None
            state.emergency.ack_sent = False
            state.emergency.started_monotonic = None

            state.mark_seen()

            return True

    def call_started(
        self,
        railing_id: int,
        origin: int,
        direction: int,
    ) -> None:
        from time import monotonic

        with self._lock:
            state = self._get_or_create_locked(
                railing_id
            )

            state.mark_seen()

            state.call.active = True
            state.call.origin = origin
            state.call.direction = direction
            state.call.started_monotonic = monotonic()

    def call_direction_changed(
        self,
        railing_id: int,
        direction: int,
    ) -> bool:
        with self._lock:
            state = self._states.get(
                railing_id
            )

            if (
                state is None
                or not state.call.active
            ):
                return False

            state.mark_seen()
            state.call.direction = direction

            return True

    def call_ended(
        self,
        railing_id: int,
    ) -> bool:
        with self._lock:
            state = self._states.get(
                railing_id
            )

            if state is None:
                return False

            state.mark_seen()

            state.call.active = False
            state.call.origin = None
            state.call.direction = None
            state.call.started_monotonic = None

            return True

    def get_active_emergency(
        self,
        railing_id: int,
    ) -> tuple[int, int] | None:
        with self._lock:
            state = self._states.get(
                railing_id
            )

            if (
                state is None
                or not state.emergency.active
                or state.emergency.seq is None
                or state.emergency.source is None
            ):
                return None

            return (
                state.emergency.source,
                state.emergency.seq,
            )

    def snapshot(
        self,
        railing_id: int | None = None,
    ) -> dict:
        with self._lock:
            if railing_id is not None:
                state = self._states.get(
                    railing_id
                )
                return (
                    {}
                    if state is None
                    else asdict(state)
                )

            return {
                rid: asdict(state)
                for rid, state in sorted(
                    self._states.items()
                )
            }
