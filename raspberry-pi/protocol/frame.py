from __future__ import annotations

from dataclasses import dataclass

from .constants import (
    CRC_SIZE,
    HEADER_SIZE,
    MAX_FRAME_SIZE,
    MAX_PAYLOAD,
    SOF1,
    SOF2,
)


class ProtocolError(ValueError):
    pass


def crc16_ccitt_false(data: bytes) -> int:
    crc = 0xFFFF

    for value in data:
        crc ^= value << 8

        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF

    return crc


@dataclass(frozen=True, slots=True)
class Frame:
    railing_id: int
    src: int
    dst: int
    service: int
    command: int
    payload: bytes = b""

    def __post_init__(self) -> None:
        if not 0 <= self.railing_id <= 0xFF:
            raise ProtocolError("railing_id must fit in one byte")

        for name in ("src", "dst", "service", "command"):
            value = getattr(self, name)
            if not 0 <= int(value) <= 0xFF:
                raise ProtocolError(f"{name} must fit in one byte")

        if not isinstance(self.payload, bytes):
            object.__setattr__(self, "payload", bytes(self.payload))

        if len(self.payload) > MAX_PAYLOAD:
            raise ProtocolError(
                f"payload too large: {len(self.payload)} > {MAX_PAYLOAD}"
            )

    @property
    def payload_len(self) -> int:
        return len(self.payload)

    def encode(self) -> bytes:
        crc_data = bytes(
            [
                self.payload_len,
                self.railing_id,
                int(self.src),
                int(self.dst),
                int(self.service),
                int(self.command),
            ]
        ) + self.payload

        crc = crc16_ccitt_false(crc_data)

        return (
            bytes([SOF1, SOF2])
            + crc_data
            + crc.to_bytes(2, "big")
        )

    @classmethod
    def decode(cls, data: bytes) -> "Frame":
        if len(data) < HEADER_SIZE + CRC_SIZE:
            raise ProtocolError("frame too short")

        if data[0] != SOF1 or data[1] != SOF2:
            raise ProtocolError("invalid SOF")

        payload_len = data[2]

        if payload_len > MAX_PAYLOAD:
            raise ProtocolError("payload length exceeds protocol maximum")

        expected_len = HEADER_SIZE + payload_len + CRC_SIZE

        if expected_len > MAX_FRAME_SIZE:
            raise ProtocolError("invalid frame size")

        if len(data) != expected_len:
            raise ProtocolError(
                f"frame length mismatch: got={len(data)} expected={expected_len}"
            )

        crc_index = HEADER_SIZE + payload_len
        received_crc = int.from_bytes(
            data[crc_index : crc_index + 2],
            "big",
        )

        calculated_crc = crc16_ccitt_false(
            data[2:crc_index]
        )

        if received_crc != calculated_crc:
            raise ProtocolError(
                f"CRC mismatch: received=0x{received_crc:04X} "
                f"calculated=0x{calculated_crc:04X}"
            )

        return cls(
            railing_id=data[3],
            src=data[4],
            dst=data[5],
            service=data[6],
            command=data[7],
            payload=bytes(data[8:crc_index]),
        )


def read_u32_be(data: bytes) -> int:
    if len(data) != 4:
        raise ProtocolError("u32 requires exactly 4 bytes")

    return int.from_bytes(data, "big")


def write_u32_be(value: int) -> bytes:
    if not 0 <= value <= 0xFFFFFFFF:
        raise ProtocolError("u32 out of range")

    return value.to_bytes(4, "big")
