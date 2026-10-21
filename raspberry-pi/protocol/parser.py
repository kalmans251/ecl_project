from __future__ import annotations

import logging
import time

from .constants import HEADER_SIZE, MAX_PAYLOAD, SOF1, SOF2
from .frame import Frame, ProtocolError


LOG = logging.getLogger(__name__)


class FrameParser:
    def __init__(self, idle_timeout: float = 0.2) -> None:
        if idle_timeout <= 0:
            raise ValueError("idle_timeout must be positive")
        self._buffer = bytearray()
        self._idle_timeout = idle_timeout
        self._last_data_at: float | None = None

    def reset(self) -> None:
        self._buffer.clear()
        self._last_data_at = None

    def expire(self, now: float | None = None) -> bool:
        """Discard an incomplete candidate after a host-observed RX idle gap.

        This is not a total-frame deadline. Each received chunk restarts it.
        Only the RX thread should call feed/expire/reset while the bus is open.
        """
        now = time.monotonic() if now is None else now
        if (not self._buffer or self._last_data_at is None
                or now - self._last_data_at < self._idle_timeout):
            return False
        expected = (HEADER_SIZE + self._buffer[2] + 2
                    if len(self._buffer) >= 3 else None)
        LOG.debug("PLC incomplete frame expired: received=%d expected=%s idle=%.3fs raw=%s",
                  len(self._buffer), expected, now - self._last_data_at,
                  self._buffer.hex(" "))
        self.reset()
        return True

    @property
    def pending_bytes(self) -> int:
        return len(self._buffer)

    def feed(self, data: bytes) -> list[Frame]:
        now = time.monotonic()
        # Check before appending so a new response cannot finish a stale one,
        # even if the reader did not get an empty read during the gap.
        self.expire(now)
        if data:
            self._buffer.extend(data)
            self._last_data_at = now

        frames: list[Frame] = []

        while True:
            if len(self._buffer) < 2:
                break

            sof_index = self._buffer.find(
                bytes([SOF1, SOF2])
            )

            if sof_index < 0:
                if self._buffer[-1] == SOF1:
                    self._buffer[:] = self._buffer[-1:]
                else:
                    self._buffer.clear()
                break

            if sof_index > 0:
                del self._buffer[:sof_index]

            if len(self._buffer) < 3:
                break

            payload_len = self._buffer[2]

            if payload_len > MAX_PAYLOAD:
                del self._buffer[0]
                continue

            total_len = HEADER_SIZE + payload_len + 2

            if len(self._buffer) < total_len:
                break

            candidate = bytes(
                self._buffer[:total_len]
            )

            try:
                frame = Frame.decode(candidate)
            except ProtocolError as exc:
                LOG.debug("PLC frame rejected: %s raw=%s", exc, candidate.hex(" "))
                # Drop one byte, then search for the next SOF.
                del self._buffer[0]
                continue

            del self._buffer[:total_len]
            frames.append(frame)

        return frames
