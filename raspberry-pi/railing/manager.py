from __future__ import annotations

import threading
import json
import os
import tempfile
from pathlib import Path
from dataclasses import asdict

from .state import RailingState


class RailingManager:
    def __init__(self, state_file: str | None = None) -> None:
        self._states: dict[int, RailingState] = {}
        self._lock = threading.RLock()
        self._state_file = Path(state_file).expanduser() if state_file else None
        if self._state_file is not None:
            if self._state_file.exists():
                data = json.loads(self._state_file.read_text())
                if data.get("version") != 1 or not isinstance(data.get("pending"), list):
                    raise ValueError("Invalid call recovery journal")
                for rid in data["pending"]:
                    if type(rid) is not int or not 1 <= rid <= 255:
                        raise ValueError("Invalid railing ID in call recovery journal")
                    self._get_or_create_locked(rid).call.phase = "unknown"
                    self._get_or_create_locked(rid).call.recovered = True
            self._save_calls_locked()

    def _save_calls_locked(self) -> None:
        if self._state_file is None:
            return
        pending = [rid for rid, state in self._states.items()
                   if state.call.active or state.call.phase not in ("idle", "ended")]
        path = self._state_file
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
        try:
            with os.fdopen(fd, "w") as stream:
                json.dump({"version": 1, "pending": sorted(pending)}, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

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

    def reserve_call(self, railing_id: int, *, emergency: bool = False) -> None:
        """Atomically reserve the shared bus before a request can reach hardware."""
        with self._lock:
            for rid, state in self._states.items():
                if state.call.phase not in ("idle", "ended") or state.call.active:
                    raise RuntimeError(f"Another or unresolved call owns PLC rail={rid}; hangup first")
                if not emergency and state.emergency.active:
                    raise RuntimeError("An emergency is active; use ack for the emergency call")
            self._get_or_create_locked(railing_id).call.recovered = False
            self._get_or_create_locked(railing_id).call.phase = "starting"
            self._save_calls_locked()

    def call_request_failed(self, railing_id: int) -> None:
        with self._lock:
            call = self._get_or_create_locked(railing_id).call
            if call.phase in ("starting", "ending"):
                call.phase = "unknown"

    def call_end_requested(self, railing_id: int) -> None:
        with self._lock:
            self._get_or_create_locked(railing_id).call.phase = "ending"

    def call_pending(self, railing_id: int) -> bool:
        with self._lock:
            state = self._states.get(railing_id)
            return state is not None and (state.call.active or
                state.call.phase not in ("idle", "ended"))

    def call_started(
        self,
        railing_id: int,
        origin: int,
        direction: int,
    ) -> bool:
        from time import monotonic

        with self._lock:
            state = self._get_or_create_locked(
                railing_id
            )

            if state.call.recovered:
                return False
            state.mark_seen()

            state.call.phase = "active"
            state.call.active = True
            state.call.origin = origin
            state.call.direction = direction
            state.call.started_monotonic = monotonic()
            self._save_calls_locked()
            return True

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

            state.call.recovered = False
            state.call.phase = "ended"
            state.call.active = False
            state.call.origin = None
            state.call.direction = None
            state.call.started_monotonic = None
            self._save_calls_locked()

            return True

    def get_call_direction(
        self,
        railing_id: int,
    ) -> int | None:
        with self._lock:
            state = self._states.get(
                railing_id
            )

            if (
                state is None
                or not state.call.active
                or state.call.direction is None
            ):
                return None

            return state.call.direction

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
