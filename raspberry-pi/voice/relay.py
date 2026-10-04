from __future__ import annotations

import logging
import socket
import threading

from plc import PlcBus
from protocol import (
    AudioDataType,
    AudioDirection,
    Command,
    Frame,
    Node,
    Service,
)
from railing import RailingManager

from .packet import (
    VoicePacket,
    VoicePacketError,
    VoiceStreamParser,
)


LOG = logging.getLogger(__name__)


class VoiceRelay:
    """
    Codec2 packet relay only.

    No PCM processing and no Codec2 encode/decode happens
    on the Raspberry Pi.
    """

    def __init__(
        self,
        bus: PlcBus,
        railings: RailingManager,
        host: str = "0.0.0.0",
        port: int = 9100,
    ) -> None:
        self._bus = bus
        self._railings = railings
        self.host = host
        self.port = port

        self._server: socket.socket | None = None
        self._stop_event = threading.Event()
        self._accept_thread: threading.Thread | None = None

        self._clients: set[socket.socket] = set()
        self._clients_lock = threading.Lock()

        self.field_packets = 0
        self.control_packets = 0
        self.dropped_packets = 0

    def start(self) -> None:
        if self._server is not None:
            return

        server = socket.socket(
            socket.AF_INET,
            socket.SOCK_STREAM,
        )

        server.setsockopt(
            socket.SOL_SOCKET,
            socket.SO_REUSEADDR,
            1,
        )

        server.bind(
            (
                self.host,
                self.port,
            )
        )

        server.listen(4)
        server.settimeout(0.5)

        self._server = server
        self._stop_event.clear()

        self._accept_thread = threading.Thread(
            target=self._accept_loop,
            name="voice-tcp-accept",
            daemon=True,
        )

        self._accept_thread.start()

        LOG.info(
            "Voice relay listening on %s:%d",
            self.host,
            self.port,
        )

    def close(self) -> None:
        self._stop_event.set()

        server = self._server
        self._server = None

        if server is not None:
            try:
                server.close()
            except OSError:
                pass

        with self._clients_lock:
            clients = list(
                self._clients
            )
            self._clients.clear()

        for client in clients:
            try:
                client.shutdown(
                    socket.SHUT_RDWR
                )
            except OSError:
                pass

            try:
                client.close()
            except OSError:
                pass

        thread = self._accept_thread
        self._accept_thread = None

        if thread is not None:
            thread.join(
                timeout=1.0
            )

        LOG.info("Voice relay stopped")

    def handle_plc_frame(
        self,
        frame: Frame,
    ) -> bool:
        if (
            int(frame.service)
            != int(Service.AUDIO)
            or int(frame.command)
            != int(Command.DATA)
            or int(frame.dst)
            != int(Node.PI)
            or len(frame.payload) < 1
            or frame.payload[0]
            != int(AudioDataType.CODEC2)
        ):
            return False

        try:
            packet = (
                VoicePacket.from_audio_payload(
                    frame.railing_id,
                    frame.payload,
                )
            )
        except VoicePacketError as exc:
            self.dropped_packets += 1

            LOG.warning(
                "Drop invalid FIELD Codec2 packet "
                "rail=%d: %s",
                frame.railing_id,
                exc,
            )

            return True

        if (
            packet.direction
            != int(
                AudioDirection.FIELD_TX
            )
        ):
            self.dropped_packets += 1

            LOG.warning(
                "Drop PLC voice packet with "
                "non-FIELD direction rail=%d dir=%d",
                packet.railing_id,
                packet.direction,
            )

            return True

        if (
            self._railings.get_call_direction(
                packet.railing_id
            )
            != int(
                AudioDirection.FIELD_TX
            )
        ):
            self.dropped_packets += 1

            LOG.debug(
                "Drop FIELD packet outside FIELD_TX "
                "rail=%d seq=%d",
                packet.railing_id,
                packet.sequence,
            )

            return True

        self.field_packets += 1

        self._broadcast(
            packet.encode_network()
        )

        if (
            self.field_packets == 1
            or self.field_packets % 25 == 0
        ):
            LOG.info(
                "FIELD Codec2 -> control center "
                "rail=%d seq=%d frames=%d packets=%d",
                packet.railing_id,
                packet.sequence,
                packet.frame_count,
                self.field_packets,
            )

        return True

    def forward_control_packet(
        self,
        packet: VoicePacket,
    ) -> bool:
        if (
            packet.direction
            != int(
                AudioDirection.CONTROL_TX
            )
        ):
            self.dropped_packets += 1

            LOG.warning(
                "Reject control-center packet "
                "with direction=%d",
                packet.direction,
            )

            return False

        if (
            self._railings.get_call_direction(
                packet.railing_id
            )
            != int(
                AudioDirection.CONTROL_TX
            )
        ):
            self.dropped_packets += 1

            LOG.debug(
                "Drop CONTROL packet outside CONTROL_TX "
                "rail=%d seq=%d",
                packet.railing_id,
                packet.sequence,
            )

            return False

        frame = Frame(
            railing_id=packet.railing_id,
            src=Node.PI,
            dst=Node.WROOM,
            service=Service.AUDIO,
            command=Command.DATA,
            payload=packet.to_audio_payload(),
        )

        self._bus.send_frame(
            frame
        )

        self.control_packets += 1

        if (
            self.control_packets == 1
            or self.control_packets % 25 == 0
        ):
            LOG.info(
                "CONTROL Codec2 -> PLC "
                "rail=%d seq=%d frames=%d packets=%d",
                packet.railing_id,
                packet.sequence,
                packet.frame_count,
                self.control_packets,
            )

        return True

    def client_count(self) -> int:
        with self._clients_lock:
            return len(
                self._clients
            )

    def _accept_loop(self) -> None:
        while not self._stop_event.is_set():
            server = self._server

            if server is None:
                return

            try:
                client, address = (
                    server.accept()
                )
            except socket.timeout:
                continue
            except OSError:
                if not self._stop_event.is_set():
                    LOG.exception(
                        "Voice accept failed"
                    )
                return

            client.settimeout(0.5)

            with self._clients_lock:
                self._clients.add(
                    client
                )

            LOG.info(
                "Voice client connected %s:%d",
                address[0],
                address[1],
            )

            threading.Thread(
                target=self._client_loop,
                args=(
                    client,
                    address,
                ),
                name=(
                    f"voice-client-"
                    f"{address[0]}:{address[1]}"
                ),
                daemon=True,
            ).start()

    def _client_loop(
        self,
        client: socket.socket,
        address: tuple[str, int],
    ) -> None:
        parser = VoiceStreamParser()

        try:
            while not self._stop_event.is_set():
                try:
                    data = client.recv(
                        4096
                    )
                except socket.timeout:
                    continue

                if not data:
                    break

                for packet in parser.feed(
                    data
                ):
                    self.forward_control_packet(
                        packet
                    )

        except OSError:
            if not self._stop_event.is_set():
                LOG.exception(
                    "Voice client receive failed"
                )

        finally:
            with self._clients_lock:
                self._clients.discard(
                    client
                )

            try:
                client.close()
            except OSError:
                pass

            LOG.info(
                "Voice client disconnected %s:%d",
                address[0],
                address[1],
            )

    def _broadcast(
        self,
        data: bytes,
    ) -> None:
        with self._clients_lock:
            clients = list(
                self._clients
            )

        dead: list[socket.socket] = []

        for client in clients:
            try:
                client.sendall(
                    data
                )
            except OSError:
                dead.append(
                    client
                )

        if dead:
            with self._clients_lock:
                for client in dead:
                    self._clients.discard(
                        client
                    )

                    try:
                        client.close()
                    except OSError:
                        pass
