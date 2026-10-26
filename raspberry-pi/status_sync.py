"""Bounded controller status snapshots over the existing single PLC reader."""
from datetime import datetime, timezone
import logging
import threading
import time
from music_info import request
from protocol import Service, Node, Command
LOG=logging.getLogger('status.sync')

def decode(data):
    if (len(data)!=16 or data[0]!=1 or data[1] not in (0,1,2) or
        any(data[i] not in (0,1) for i in (2,3,6,7,8,9,15)) or
        data[4] not in (1,2,3) or data[5]>3 or data[10] not in (1,2,3)):
        raise ValueError('Invalid P4 status snapshot; update P4 firmware')
    state=dict(power_on=bool(data[2]),led_enabled=bool(data[3]),
        led={1:'basic',2:'weather',3:'music'}[data[4]],
        weather=('clear','cloudy','rain','snow')[data[5]],projector=bool(data[6]),
        sleep=bool(data[7]),sleep_active=bool(data[8]),
        detection=('radar','cctv')[data[9]],music_mode=('sequential','shuffle','age')[data[10]-1],
        detection_count=int.from_bytes(data[11:15],'big'))
    if data[1]: state['power']=('ac','battery')[data[1]-1]
    return state

class StatusSync:
    def __init__(self, controls, audio, rails, publisher, outbox=None):
        self.outbox=outbox
        self.controls,self.audio,self.rails,self.publisher=controls,audio,tuple(rails),publisher
        self.stop=threading.Event();self.thread=None;self.due={};self.emergencies={}
        self.lock=threading.Lock();self.wanted={}
    def demand(self, message):
        ids=message.get('rails')
        if type(message.get('version')) is not int or message['version']!=1 or not isinstance(ids,list) or len(ids)>255:
            raise ValueError('Invalid status demand')
        with self.lock:
            self.wanted={r:time.monotonic()+6 for r in ids if type(r) is int and r in self.rails}
    def disconnect(self):
        with self.lock:self.wanted.clear()
    def wanted_now(self, rail):
        with self.lock:return self.wanted.get(rail,0)>time.monotonic()
    def emergency(self, rail):
        if rail not in self.rails: return
        e=self.controls.railings.snapshot(rail).get('emergency',{})
        identity=(e.get('active',False),e.get('seq'))
        if self.outbox:self.outbox.record(rail,identity)
    def sample(self, rail):
        if not self.publisher.connected.is_set() or not self.wanted_now(rail): return False
        def guard():
            if self.audio._keepalive_due.is_set() or not self.publisher.connected.is_set() or not self.wanted_now(rail):
                raise RuntimeError('Priority control or disconnected')
        try:
            state=decode(request(self.controls,rail,Command.STATUS_REQUEST,b'\x01',
                background=True,timeout=.6,service=Service.SYSTEM,expected=Node.P4,control_lock=self.audio._control_lock,guard=guard))
        except (RuntimeError,ValueError,OSError) as exc:
            LOG.debug('Status not refreshed rail=%s: %s',rail,exc)
            return False
        if not self.publisher.connected.is_set() or not self.wanted_now(rail): return False
        self.publisher.publish(dict(version=1,type='telemetry',railing_id=rail,
            observed_at=datetime.now(timezone.utc).isoformat(),state=state))
        return True
    def start(self):
        self.thread=threading.Thread(target=self._run,name='status-poll',daemon=True);self.thread.start()
    def _run(self):
        while not self.stop.wait(.5):
            if not self.publisher.connected.is_set(): continue
            now=time.monotonic()
            candidates=[r for r in self.rails if self.wanted_now(r) and self.due.get(r,0)<=now]
            if not candidates: continue
            rail=min(candidates,key=lambda r:self.due.get(r,0))
            self.sample(rail);self.due[rail]=time.monotonic()+5
    def close(self):
        self.stop.set()
        if self.thread:self.thread.join(2)
