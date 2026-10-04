from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

import serial

from protocol import Frame, FrameParser


LOG = logging.getLogger(__name__)


class PlcBus:
    def __init__(
        self,
        port: str = "/dev/ttyAMA2",
        baudrate: int = 9600,
        read_timeout: float = 0.05,
        tx_guard_seconds: float = 0.0,
    ) -> None:
        self.port = port
        self.baudrate = baudrate
        self.read_timeout = read_timeout
        self.tx_guard_seconds = tx_guard_seconds

        self._serial: serial.Serial | None = None
        self._parser = FrameParser()
        self._tx_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._reader_thread: threading.Thread | None = None
        self._frame_handler: Callable[[Frame], None] | None = None

    def set_frame_handler(
        self,
        handler: Callable[[Frame], None],
    ) -> None:
        self._frame_handler = handler

    def open(self) -> None:
        if self._serial is not None:
            return

        self._serial = serial.Serial(
            port=self.port,
            baudrate=self.baudrate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=self.read_timeout,
            write_timeout=0.5,
        )

        self._stop_event.clear()

        self._reader_thread = threading.Thread(
            target=self._reader_loop,
            name="plc-rx",
            daemon=True,
        )
        self._reader_thread.start()

        LOG.info(
            "PLC opened port=%s baud=%d",
            self.port,
            self.baudrate,
        )

    def close(self) -> None:
        self._stop_event.set()

        thread = self._reader_thread
        if thread is not None:
            thread.join(timeout=1.0)

        self._reader_thread = None

        serial_port = self._serial
        self._serial = None

        if serial_port is not None:
            serial_port.close()

        self._parser.reset()

        LOG.info("PLC closed")

    def send_frame(self, frame: Frame) -> None:
        raw = frame.encode()

        serial_port = self._serial

        if serial_port is None:
            raise RuntimeError("PLC serial port is not open")

        with self._tx_lock:
            if self.tx_guard_seconds > 0:
                time.sleep(self.tx_guard_seconds)

            written = serial_port.write(raw)
            serial_port.flush()

            if written != len(raw):
                raise IOError(
                    f"short serial write: {written}/{len(raw)}"
                )

        LOG.debug(
            "PLC TX rail=%02X src=%02X dst=%02X service=%02X cmd=%02X "
            "payload=%d raw=%s",
            frame.railing_id,
            int(frame.src),
            int(frame.dst),
            int(frame.service),
            int(frame.command),
            frame.payload_len,
            raw.hex(" "),
        )

    def _reader_loop(self) -> None:
        while not self._stop_event.is_set():
            serial_port = self._serial

            if serial_port is None:
                return

            try:
                waiting = serial_port.in_waiting

                read_size = min(
                    max(waiting, 1),
                    512,
                )

                data = serial_port.read(
                    read_size
                )

                if not data:
                    continue

                for frame in self._parser.feed(data):
                    LOG.debug(
                        "PLC RX rail=%02X src=%02X dst=%02X "
                        "service=%02X cmd=%02X payload=%d",
                        frame.railing_id,
                        int(frame.src),
                        int(frame.dst),
                        int(frame.service),
                        int(frame.command),
                        frame.payload_len,
                    )

                    handler = self._frame_handler
                    if handler is not None:
                        try:
                            handler(frame)
                        except Exception:
                            LOG.exception(
                                "Unhandled exception in PLC frame handler"
                            )

            except serial.SerialException:
                if not self._stop_event.is_set():
                    LOG.exception("PLC serial receive failed")
                return
