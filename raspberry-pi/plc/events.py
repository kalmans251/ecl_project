"""Round-robin retrieval of retained emergency reports; no automatic call ACK."""
import logging
import secrets
import threading
import time
from contextlib import nullcontext
from protocol import Frame, Node, Service, Command, AudioDirection, AudioDataType, AudioEvent

LOG = logging.getLogger(__name__)


class EventPoller:
    def __init__(self, bus, railings, audio, ids, dispatch):
        self.bus, self.railings, self.audio = bus, railings, audio
        self.ids, self.dispatch = tuple(ids), dispatch
        self.stop_event = threading.Event()
        self.condition = threading.Condition()
        self.pending = None
        self.received = False
        self.ack = {}
        self.overflow = {}
        self.token = secrets.randbits(32)
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self._run, name='event-poll', daemon=True)
        self.thread.start()

    def close(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=5.0)

    def _run(self):
        index = 0
        while not self.stop_event.wait(0.25):
            rail = self.ids[index]
            try:
                if self.poll_once(rail):
                    index = (index + 1) % len(self.ids)
            except Exception:
                LOG.warning('Emergency poll failed rail=%d; report remains pending on P4', rail,
                            exc_info=True)
                index = (index + 1) % len(self.ids)

    def poll_once(self, rail):
        # The call controller's lock makes explicit PTT/hangup take priority.
        if self.audio._keepalive_due.is_set() or not self.audio._control_lock.acquire(False):
            return False
        try:
            states = self.railings.snapshot()
            calls = [(rid, s['call']) for rid, s in states.items()
                     if s['call']['phase'] not in ('idle', 'ended') or s['call']['active']]
            if len(calls) > 1 or (calls and calls[0][1]["phase"] in ("starting", "ending")):
                return False
            owner = calls[0][0] if calls else None
            field = bool(calls and calls[0][1]['direction'] != int(AudioDirection.CONTROL_TX))
            with getattr(self.bus, 'transaction', nullcontext)():
                self.token = (self.token + 1) & 0xffffffff
                token = self.token.to_bytes(4, 'big')
                request = Frame(rail, Node.PI, Node.P4, Service.SYSTEM, Command.EVENT_POLL,
                                token + self.ack.get(rail, 0).to_bytes(4, 'big'))
                with self.condition:
                    self.pending = (rail, token)
                    self.received = False
                try:
                    if field:
                        try:
                            self.bus.send_control_frame(request, wait_for_window=True, timeout=0.8,
                                grant_railing=owner, reply_budget_ms=120)
                        except TimeoutError:
                            if self.audio.recovery_delay(owner)>0:
                                return True
                            self.bus.send_frame(request)
                    else:
                        # Finish preceding Pi audio and leave modem turnaround.
                        time.sleep(0.025)
                        self.bus.send_frame(request)
                    deadline = time.monotonic() + 0.12
                    with self.condition:
                        while not self.received:
                            remaining = deadline - time.monotonic()
                            if remaining <= 0:
                                LOG.debug('No emergency poll reply rail=%d', rail)
                                break
                            self.condition.wait(remaining)
                finally:
                    with self.condition:
                        self.pending = None
            return True
        finally:
            self.audio._control_lock.release()

    def handle_frame(self, frame):
        if (frame.src != Node.P4 or frame.dst != Node.PI or frame.service != Service.SYSTEM
                or frame.command != Command.EVENT_REPLY):
            return False
        if len(frame.payload) not in (14, 18, 19):
            return True
        with self.condition:
            if self.pending != (frame.railing_id, frame.payload[:4]):
                return True
            rid = frame.railing_id
            event_id = int.from_bytes(frame.payload[4:8], 'big')
            dropped = int.from_bytes(frame.payload[8:12], 'big')
            service, command = frame.payload[12:14]
            if event_id:
                emergency = (len(frame.payload)==19 and service==Service.EMERGENCY
                             and command in (Command.START, Command.STOP))
                ended = (len(frame.payload)==18 and service==Service.AUDIO and command==Command.DATA
                         and frame.payload[14]==AudioDataType.EVENT and frame.payload[15]==AudioEvent.CALL_ENDED)
                if not (emergency or ended):
                    return True
                if self.ack.get(rid) != event_id:
                    self.dispatch(Frame(rid, Node.P4, Node.PI, service, command, frame.payload[14:]))
                    # Acknowledge only after the normal event handler succeeded.
                    self.ack[rid] = event_id
            elif len(frame.payload) != 14 or service != 0 or command != 0:
                return True
            if dropped != self.overflow.get(rid, 0):
                LOG.error('Emergency reports lost on P4 rail=%d total=%d; inspect field state', rid, dropped)
            self.overflow[rid] = dropped
            self.received = True
            self.condition.notify_all()
        return True
