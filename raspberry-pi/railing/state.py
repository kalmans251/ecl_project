from __future__ import annotations

from dataclasses import dataclass, field
from time import monotonic


@dataclass(slots=True)
class EmergencyState:
    active: bool = False
    seq: int | None = None
    source: int | None = None
    ack_sent: bool = False
    started_monotonic: float | None = None


@dataclass(slots=True)
class RailingState:
    railing_id: int
    online: bool = False
    last_seen_monotonic: float | None = None
    emergency: EmergencyState = field(
        default_factory=EmergencyState
    )

    def mark_seen(self) -> None:
        self.online = True
        self.last_seen_monotonic = monotonic()
