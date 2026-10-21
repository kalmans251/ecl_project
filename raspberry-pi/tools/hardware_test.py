#!/usr/bin/env python3
"""Pi-only integration tests using production PLC/audio managers; no server required."""
from __future__ import annotations
import argparse
import csv
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import statistics
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from audio import AudioManager
from device_control import DeviceControls, HELP
from emergency import EmergencyManager
from plc import PlcBus
from plc.events import EventPoller
from protocol import AudioDirection, AudioDataType, Command, Node, Service
from railing import RailingManager
from voice import VoiceRelay


class Report:
    def __init__(self, directory):
        self.directory=Path(directory)
        self.directory.mkdir(parents=True, exist_ok=False)
        self.stream=(self.directory/'events.jsonl').open('w',encoding='utf-8')
        self.lock=threading.RLock()
        self.results=[]

    def event(self, kind, **fields):
        row={'at':datetime.now(timezone.utc).isoformat(),'kind':kind,**fields}
        with self.lock:
            self.stream.write(json.dumps(row,ensure_ascii=False,default=str)+'\n');self.stream.flush()
        return row

    def result(self, operation, status, elapsed_ms, detail):
        with self.lock:
            row=self.event('result',operation=operation,status=status,elapsed_ms=round(elapsed_ms,2),detail=detail)
            self.results.append(row)
        print(f'[{status}] {operation} ({elapsed_ms:.0f} ms): {detail}')

    def close(self):
        with self.lock:
            with (self.directory/'results.csv').open('w',newline='',encoding='utf-8-sig') as out:
                writer=csv.DictWriter(out,fieldnames=['at','operation','status','elapsed_ms','detail'],extrasaction='ignore')
                writer.writeheader();writer.writerows(self.results)
            groups={}
            for row in self.results: groups.setdefault(row['operation'],[]).append(row)
            summary={op:{'attempts':len(rows),'statuses':{s:sum(r['status']==s for r in rows) for s in sorted({r['status'] for r in rows})},
                         'confirmed_rate':round(sum(r['status']=='PASS' for r in rows)/len(rows),4),
                         'mean_ms':round(statistics.mean(r['elapsed_ms'] for r in rows),2),
                         'max_ms':max(r['elapsed_ms'] for r in rows)} for op,rows in groups.items()}
            (self.directory/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8')
            self.stream.close()


class Rig:
    def __init__(self,args,report):
        self.args,self.report=args,report
        # Share the same recovery file as main.py; never erase an unresolved call.
        self.states=RailingManager(state_file=args.call_state_file)
        self.bus=PlcBus(port=args.port,baudrate=args.baud)
        self.audio=AudioManager(self.bus,self.states)
        self.emergency=EmergencyManager(self.bus,self.states,audio=self.audio)
        self.voice=VoiceRelay(self.bus,self.states,host='127.0.0.1')
        self.controls=DeviceControls(self.bus,self.states,self.voice,ack_timeout=args.timeout)
        self.poller=EventPoller(self.bus,self.states,self.audio,args.rails,self.on_frame)
        self.local=None
        self.owned=set()
        self.rx_control=0

    def on_frame(self,frame):
        if frame.dst!=Node.PI or frame.railing_id==0:return
        voice=(frame.service==Service.AUDIO and frame.command==Command.DATA and frame.payload
               and frame.payload[0]==AudioDataType.CODEC2)
        if not voice:
            self.rx_control+=1
            self.report.event('control_rx',rail=frame.railing_id,src=int(frame.src),service=int(frame.service),
                              command=int(frame.command),payload=frame.payload.hex())
        self.states.mark_seen(frame.railing_id)
        if self.poller.handle_frame(frame) or self.controls.handle_frame(frame):return
        if self.emergency.handle_frame(frame) or self.audio.handle_frame(frame):
            self.voice.state_changed();return
        self.voice.handle_plc_frame(frame)

    def open(self):
        self.bus.set_frame_handler(self.on_frame)
        self.bus.open()
        # No TCP voice listener or monitoring connection is started.
        if self.args.local_audio:
            from voice.local_audio import LocalAudio
            self.local=LocalAudio(self.voice,self.args.audio_railing,self.args.mic_device,self.args.speaker_device)
            self.local.start()
        self.audio.start_keepalive();self.poller.start()

    def snapshot(self):
        return {'rails':self.states.snapshot(),'field_packets':self.voice.field_packets,
                'control_packets':self.voice.control_packets,'dropped_packets':self.voice.dropped_packets,
                'control_rx':self.rx_control,'local_audio':self.local.status() if self.local else None}

    def idle(self):
        if any(self.states.call_pending(rid) for rid in self.states.snapshot()):
            raise RuntimeError('Unresolved call: use manual mode and hangup <id> first; do not delete the journal')

    def execute(self,line):
        parts=line.split()
        if not parts:raise ValueError('Empty command')
        name=parts[0].lower()
        if len(parts)<2:raise ValueError('A railing ID is required')
        rid=int(parts[1])
        if rid not in self.args.rails:raise ValueError('Railing is not in --rails')
        if name in ('call','ack','hangup','ptt'):
            if len(parts)!=(3 if name=='ptt' else 2):raise ValueError('Invalid call command syntax')
            if name=='ptt' and parts[2] not in ('on','off'):raise ValueError('Use ptt <id> on|off')
            if name in ('call','ack'):
                self.idle();self.owned.add(rid)
            with self.voice.control_transition():
                if name=='call':
                    if not self.audio.start_call(rid):raise RuntimeError('No new call confirmation')
                elif name=='ack':self.emergency.ack(rid)
                elif name=='hangup':
                    if not self.audio.end_call(rid):raise RuntimeError('Locally idle; no remote END confirmation was obtained')
                else:self.audio.set_direction(rid,AudioDirection.CONTROL_TX if parts[2]=='on' else AudioDirection.FIELD_TX)
            self.voice.state_changed()
            return 'PASS','Device call confirmation received; sound quality not assessed'
        result=self.controls.execute(parts)
        if result is None:raise ValueError('Unsupported command; use main.py help syntax')
        return ('POLICY_ONLY' if 'playback not confirmed' in result else 'PASS'),result

    def step(self,line):
        started=time.monotonic()
        try:status,detail=self.execute(line)
        except Exception as exc:status,detail='FAIL',f'{type(exc).__name__}: {exc}'
        self.report.result(line,status,(time.monotonic()-started)*1000,detail)
        self.report.event('snapshot',**self.snapshot())
        return status!='FAIL'

    def cleanup_calls(self):
        ok=True
        for rid in sorted(self.owned):
            if self.states.call_pending(rid):ok=self.step(f'hangup {rid}') and ok
        return ok

    def close(self):
        self.poller.close();self.audio.close()
        if self.local:self.local.close()
        self.voice.close();self.bus.close()


def automated(rig,args):
    rig.idle()
    for cycle in range(1,args.cycles+1):
        rig.report.event('cycle',number=cycle,suite=args.suite)
        for rid in args.rails:
            if args.suite=='communication':
                for command in (f'ping {rid}',*(f'query {rid} {node}' for node in ('p4','wroom','s3'))):
                    rig.step(command)
                    time.sleep(args.interval)
            else:
                try:
                    for command in (f'call {rid}',f'ptt {rid} on',f'ptt {rid} off',f'hangup {rid}'):
                        if not rig.step(command):return False
                        if not command.startswith('hangup'):time.sleep(args.hold)
                finally:
                    rig.cleanup_calls()
                # Never advance to another rail while the bus ownership is unresolved.
                rig.idle()
                time.sleep(args.interval)
    return True


def manual(rig):
    print('Commands: ping/query/led/music/volume/sleep/detection/power/projector, call/ptt/hangup/ack')
    print('Extra: status | wait <seconds> | check pass|fail|skip <observation> | quit')
    print('No device action is inferred from check. Judge actual sound, LED and projector yourself.')
    while True:
        line=input('test> ').strip()
        if not line:continue
        if line in ('quit','exit'):break
        if line=='help':
            print(HELP);print('call/ack/hangup <id> | ptt <id> on|off | status | wait <seconds> | check pass|fail|skip <note> | quit');continue
        if line=='status':
            state=rig.snapshot();rig.report.event('snapshot',**state);print(json.dumps(state,indent=2,ensure_ascii=False));continue
        parts=line.split(maxsplit=2)
        if parts[0]=='check':
            if len(parts)!=3 or parts[1] not in ('pass','fail','skip'):
                print('check pass|fail|skip <what you observed>');continue
            rig.report.result('human observation','HUMAN_'+parts[1].upper(),0,parts[2]);continue
        if parts[0]=='wait':
            try:
                seconds=float(parts[1])
                if not 0<seconds<=3600:raise ValueError()
                time.sleep(seconds);rig.report.event('snapshot',**rig.snapshot())
            except (ValueError,IndexError):print('wait <seconds: 0..3600>')
            continue
        rig.step(line)


def arguments(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite',choices=['communication','calls','manual'],default='communication')
    parser.add_argument('--rails',default='1')
    parser.add_argument('--cycles',type=int,default=1)
    parser.add_argument('--hold',type=float,default=2,help='Seconds in each call direction')
    parser.add_argument('--interval',type=float,default=.3)
    parser.add_argument('--timeout',type=float,default=3,help='General command response timeout')
    parser.add_argument('--port',default='/dev/serial0');parser.add_argument('--baud',type=int,default=9600)
    parser.add_argument('--call-state-file',default='~/.local/state/ecl-railing/calls.json')
    parser.add_argument('--output',help='New directory; existing results are never overwritten')
    parser.add_argument('--local-audio',action='store_true');parser.add_argument('--audio-railing',type=int)
    parser.add_argument('--mic-device');parser.add_argument('--speaker-device',default='bcm2835 Headphones')
    parser.add_argument('--list-audio-devices',action='store_true');parser.add_argument('--debug',action='store_true')
    args=parser.parse_args(argv)
    try:
        args.rails=tuple(dict.fromkeys(int(x) for x in args.rails.split(',')))
        if not args.rails or any(not 1<=x<=255 for x in args.rails):raise ValueError()
    except ValueError:parser.error('--rails requires comma-separated IDs in 1..255')
    if not 1<=args.cycles<=10000 or not 0<args.hold<=3600 or not 0<=args.interval<=60 or not 0<args.timeout<=60:
        parser.error('Invalid cycles, hold, interval or timeout')
    args.audio_railing=args.audio_railing or args.rails[0]
    if args.audio_railing not in args.rails:parser.error('--audio-railing must be in --rails')
    if args.local_audio and len(args.rails)>1:parser.error('Local audio test requires exactly one rail')
    return args


def main(argv=None):
    args=arguments(argv)
    if args.list_audio_devices:
        import sounddevice as sd
        print(sd.query_devices());return 0
    directory=args.output or ('test-results/'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    report=Report(directory)
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO,
                        format='%(asctime)s %(levelname)s %(name)s: %(message)s',
                        handlers=[logging.FileHandler(report.directory/'runtime.log',encoding='utf-8'),logging.StreamHandler()])
    report.event('configuration',**vars(args))
    rig=None;failed=False
    print('Stop main.py, monitoring services and voice_send.py before running. Run only one PLC reader; other processes are not stopped automatically.')
    try:
        rig=Rig(args,report);rig.open()
        if args.suite=='manual':manual(rig)
        else:automated(rig,args)
    except (KeyboardInterrupt,EOFError):
        failed=True;report.result('run','INTERRUPTED',0,'User interrupted; attempting confirmed hangup')
    except Exception as exc:
        failed=True;report.result('run','FAIL',0,f'{type(exc).__name__}: {exc}')
    finally:
        if rig:
            try:
                if not rig.cleanup_calls():failed=True
                report.event('final_snapshot',**rig.snapshot())
            except (Exception,KeyboardInterrupt) as exc:
                failed=True;report.result('cleanup','FAIL',0,f'{type(exc).__name__}: {exc}; unresolved call journal retained')
            finally:
                try:rig.close()
                except Exception as exc:
                    failed=True;report.result('close','FAIL',0,str(exc))
        failed=failed or any(r['status'] in ('FAIL','HUMAN_FAIL','INTERRUPTED') for r in report.results)
        report.close()
    print(f'Results: {report.directory.resolve()}')
    print('Packet/command confirmation is not proof of audible playback or multi-node collision immunity.')
    return 1 if failed else 0


if __name__=='__main__':raise SystemExit(main())
