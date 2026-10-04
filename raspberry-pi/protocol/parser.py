from __future__ import annotations

from .constants import HEADER_SIZE, MAX_PAYLOAD, SOF1, SOF2
from .frame import Frame, ProtocolError


class FrameParser:
    def __init__(self) -> None:
        self._buffer = bytearray()

    def reset(self) -> None:
        self._buffer.clear()

    def feed(self, data: bytes) -> list[Frame]:
        if data:
            self._buffer.extend(data)

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
            except ProtocolError:
                # Drop one byte, then search for the next SOF.
                del self._buffer[0]
                continue

            del self._buffer[:total_len]
            frames.append(frame)

        return frames
