from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import serial

from protocol import AudioDataType, Command, Frame, FrameParser, Node, Service


LOG = logging.getLogger(__name__)


@dataclass
class _ControlWrite:
    frame: Frame
    deadline: float
    done: threading.Event = field(default_factory=threading.Event)
    error: Exception | None = None


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
        self._pending_lock = threading.Lock()
        self._pending: list[_ControlWrite] = []

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
        with self._pending_lock:
            pending, self._pending = self._pending, []
        for request in pending:
            request.error = RuntimeError("PLC closed before control transmission")
            request.done.set()

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

    def send_control_frame(self, frame: Frame, *, wait_for_window: bool,
                           timeout: float = 1.0) -> None:
        """A single short command per fresh P4 receive grant.

        Call from the console/control thread, never from the RX callback.
        No automatic idle fallback: a missing grant must be reported.
        """
        if not wait_for_window:
            self.send_frame(frame)
            return
        if self._serial is None:
            raise RuntimeError("PLC serial port is not open")
        request = _ControlWrite(frame, time.monotonic() + timeout)
        with self._pending_lock:
            self._pending.append(request)
        if not request.done.wait(timeout):
            with self._pending_lock:
                if request in self._pending:
                    self._pending.remove(request)
                    raise TimeoutError("No fresh P4 control window; check P4 firmware")
            # RX already claimed the command. Allow its bounded serial write
            # to finish so a timed-out request cannot silently execute later.
            if not request.done.wait(0.7):
                raise TimeoutError("PLC control write did not finish")
        if request.error is not None:
            raise request.error

    @staticmethod
    def _is_control_window(frame: Frame) -> bool:
        return (int(frame.src) == int(Node.P4)
                and int(frame.dst) == int(Node.PI)
                and int(frame.service) == int(Service.AUDIO)
                and int(frame.command) == int(Command.DATA)
                and len(frame.payload) == 3
                and frame.payload[0] == int(AudioDataType.CONTROL_WINDOW))

    def _dispatch_control_window(self, grant: Frame) -> None:
        window_ms = int.from_bytes(grant.payload[1:3], "big")
        if not 20 <= window_ms <= 200:
            return
        serial_port = self._serial
        if serial_port is None or serial_port.in_waiting:
            # More bytes imply a buffered/late grant or a busy bus.
            return
        with self._pending_lock:
            request = next((r for r in self._pending
                            if r.frame.railing_id == grant.railing_id
                            and r.deadline > time.monotonic()), None)
            if request is None:
                return
            # Reserve 20 ms turnaround + 20 ms propagation/scheduling margin.
            duration_ms = len(request.frame.encode()) * 10 * 1000 / self.baudrate
            if duration_ms + 40 > window_ms:
                return
            if not self._tx_lock.acquire(blocking=False):
                return
            self._pending.remove(request)
        try:
            # Use a fixed short turnaround rather than the general TX guard.
            time.sleep(0.020)
            raw = request.frame.encode()
            written = serial_port.write(raw)
            serial_port.flush()
            if written != len(raw):
                raise IOError(f"short control write: {written}/{len(raw)}")
            LOG.info("PLC control TX in granted window rail=%d window=%dms",
                     grant.railing_id, window_ms)
        except Exception as exc:
            request.error = exc
        finally:
            self._tx_lock.release()
            request.done.set()

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
                frames = self._parser.feed(data)
                # Dispatch a fresh trailing grant before potentially slower
                # state/network callbacks. Earlier grants in a burst expired.
                if (frames and self._is_control_window(frames[-1])
                        and not self._parser.pending_bytes):
                    self._dispatch_control_window(frames[-1])
                for frame in frames:
                    if self._is_control_window(frame):
                        continue
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
