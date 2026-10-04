from __future__ import annotations

from dataclasses import dataclass
import struct

from protocol import (
    AudioDataType,
    AudioDirection,
    Codec2Mode,
)
from protocol.constants import (
    AUDIO_CODEC2_META_SIZE,
    CODEC2_2400_BYTES_PER_FRAME,
    CODEC2_MAX_FRAMES_PER_PACKET,
)


VOICE_MAGIC = b"RV"
VOICE_VERSION = 1

# magic, version, railing_id, direction, mode,
# sequence, frame_count, bytes_per_frame, data_length
_NETWORK_HEADER = struct.Struct("!2sBBBBHBBH")


class VoicePacketError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class VoicePacket:
    railing_id: int
    direction: int
    mode: int
    sequence: int
    frame_count: int
    bytes_per_frame: int
    data: bytes

    def __post_init__(self) -> None:
        if not 1 <= self.railing_id <= 0xFF:
            raise VoicePacketError(
                "railing_id must be 1..255"
            )

        if self.direction not in (
            int(AudioDirection.FIELD_TX),
            int(AudioDirection.CONTROL_TX),
        ):
            raise VoicePacketError(
                f"invalid direction: {self.direction}"
            )

        if self.mode != int(
            Codec2Mode.MODE_2400
        ):
            raise VoicePacketError(
                f"unsupported Codec2 mode: {self.mode}"
            )

        if not 0 <= self.sequence <= 0xFFFF:
            raise VoicePacketError(
                "sequence must be 0..65535"
            )

        if not (
            1
            <= self.frame_count
            <= CODEC2_MAX_FRAMES_PER_PACKET
        ):
            raise VoicePacketError(
                "invalid frame_count"
            )

        if (
            self.bytes_per_frame
            != CODEC2_2400_BYTES_PER_FRAME
        ):
            raise VoicePacketError(
                "Codec2 2400 frame must be 6 bytes"
            )

        if not isinstance(self.data, bytes):
            object.__setattr__(
                self,
                "data",
                bytes(self.data),
            )

        expected = (
            self.frame_count
            *
            self.bytes_per_frame
        )

        if len(self.data) != expected:
            raise VoicePacketError(
                f"voice data length mismatch: "
                f"got={len(self.data)} expected={expected}"
            )

    def to_audio_payload(self) -> bytes:
        return bytes(
            [
                int(AudioDataType.CODEC2),
                self.mode,
                self.direction,
            ]
        ) + self.sequence.to_bytes(
            2,
            "big",
        ) + bytes(
            [
                self.frame_count,
                self.bytes_per_frame,
            ]
        ) + self.data

    @classmethod
    def from_audio_payload(
        cls,
        railing_id: int,
        payload: bytes,
    ) -> "VoicePacket":
        if len(payload) < AUDIO_CODEC2_META_SIZE:
            raise VoicePacketError(
                "Codec2 payload too short"
            )

        if payload[0] != int(
            AudioDataType.CODEC2
        ):
            raise VoicePacketError(
                "not a Codec2 audio payload"
            )

        return cls(
            railing_id=railing_id,
            mode=payload[1],
            direction=payload[2],
            sequence=int.from_bytes(
                payload[3:5],
                "big",
            ),
            frame_count=payload[5],
            bytes_per_frame=payload[6],
            data=bytes(payload[7:]),
        )

    def encode_network(self) -> bytes:
        header = _NETWORK_HEADER.pack(
            VOICE_MAGIC,
            VOICE_VERSION,
            self.railing_id,
            self.direction,
            self.mode,
            self.sequence,
            self.frame_count,
            self.bytes_per_frame,
            len(self.data),
        )

        return header + self.data

    @classmethod
    def decode_network(
        cls,
        data: bytes,
    ) -> "VoicePacket":
        if len(data) < _NETWORK_HEADER.size:
            raise VoicePacketError(
                "network packet too short"
            )

        (
            magic,
            version,
            railing_id,
            direction,
            mode,
            sequence,
            frame_count,
            bytes_per_frame,
            data_length,
        ) = _NETWORK_HEADER.unpack(
            data[:_NETWORK_HEADER.size]
        )

        if magic != VOICE_MAGIC:
            raise VoicePacketError(
                "invalid voice magic"
            )

        if version != VOICE_VERSION:
            raise VoicePacketError(
                f"unsupported voice version: {version}"
            )

        expected = (
            _NETWORK_HEADER.size
            +
            data_length
        )

        if len(data) != expected:
            raise VoicePacketError(
                f"network length mismatch: "
                f"got={len(data)} expected={expected}"
            )

        return cls(
            railing_id=railing_id,
            direction=direction,
            mode=mode,
            sequence=sequence,
            frame_count=frame_count,
            bytes_per_frame=bytes_per_frame,
            data=bytes(
                data[_NETWORK_HEADER.size:]
            ),
        )


class VoiceStreamParser:
    def __init__(self) -> None:
        self._buffer = bytearray()

    def feed(
        self,
        data: bytes,
    ) -> list[VoicePacket]:
        if data:
            self._buffer.extend(data)

        packets: list[VoicePacket] = []

        while True:
            if len(self._buffer) < 2:
                break

            index = self._buffer.find(
                VOICE_MAGIC
            )

            if index < 0:
                if self._buffer[-1:] == VOICE_MAGIC[:1]:
                    self._buffer[:] = self._buffer[-1:]
                else:
                    self._buffer.clear()
                break

            if index > 0:
                del self._buffer[:index]

            if (
                len(self._buffer)
                <
                _NETWORK_HEADER.size
            ):
                break

            try:
                (
                    magic,
                    version,
                    _railing_id,
                    _direction,
                    _mode,
                    _sequence,
                    frame_count,
                    bytes_per_frame,
                    data_length,
                ) = _NETWORK_HEADER.unpack(
                    self._buffer[
                        :_NETWORK_HEADER.size
                    ]
                )
            except struct.error:
                break

            if (
                magic != VOICE_MAGIC
                or version != VOICE_VERSION
                or frame_count == 0
                or frame_count
                > CODEC2_MAX_FRAMES_PER_PACKET
                or bytes_per_frame
                != CODEC2_2400_BYTES_PER_FRAME
                or data_length
                != frame_count
                * bytes_per_frame
            ):
                del self._buffer[0]
                continue

            total = (
                _NETWORK_HEADER.size
                +
                data_length
            )

            if len(self._buffer) < total:
                break

            candidate = bytes(
                self._buffer[:total]
            )

            try:
                packet = (
                    VoicePacket.decode_network(
                        candidate
                    )
                )
            except VoicePacketError:
                del self._buffer[0]
                continue

            del self._buffer[:total]
            packets.append(packet)

        return packets
