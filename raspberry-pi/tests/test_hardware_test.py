import csv
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from tools.hardware_test import Report, Rig, automated, arguments, main

class HardwareRunnerTests(unittest.TestCase):
    def test_report_retains_failures_and_policy_does_not_count_as_application(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'run';r=Report(path)
            r.result('music 1 start','POLICY_ONLY',10,'policy only')
            r.result('ping 1','FAIL',100,'timeout');r.result('ping 1','PASS',20,'confirmed')
            r.close();data=json.loads((path/'summary.json').read_text())
            self.assertEqual(data['music 1 start']['confirmed_rate'],0)
            self.assertEqual(data['ping 1']['confirmed_rate'],.5)
            with (path/'results.csv').open(encoding='utf-8-sig') as f:self.assertEqual(len(list(csv.DictReader(f))),3)
            with self.assertRaises(FileExistsError):Report(path)
    def test_calls_stop_on_failed_transition_and_attempt_cleanup(self):
        class Fake:
            report=SimpleNamespace(event=lambda *a,**k:None)
            def __init__(self):self.commands=[];self.cleaned=0
            def idle(self):pass
            def step(self,line):self.commands.append(line);return not line.endswith('on')
            def cleanup_calls(self):self.cleaned+=1;return True
        rig=Fake();args=SimpleNamespace(suite='calls',cycles=5,rails=(1,2),hold=.001,interval=0)
        self.assertFalse(automated(rig,args))
        self.assertEqual(rig.commands,['call 1','ptt 1 on']);self.assertEqual(rig.cleaned,1)
    def test_invalid_ptt_cannot_send_and_foreign_rail_is_rejected(self):
        rig=Rig.__new__(Rig);rig.args=SimpleNamespace(rails=(1,))
        with self.assertRaises(ValueError):rig.execute('ptt 1 wrong')
        with self.assertRaises(ValueError):rig.execute('call 2')
    def test_general_commands_use_production_control_results(self):
        rig=Rig.__new__(Rig);rig.args=SimpleNamespace(rails=(1,))
        rig.controls=SimpleNamespace(execute=lambda p:'P4 policy confirmed; WROOM playback not confirmed')
        self.assertEqual(rig.execute('music 1 start')[0],'POLICY_ONLY')
    def test_existing_unresolved_call_is_not_automatically_owned(self):
        rig=Rig.__new__(Rig);rig.args=SimpleNamespace(rails=(1,));rig.owned=set()
        rig.states=SimpleNamespace(snapshot=lambda:{1:{}},call_pending=lambda r:True)
        with self.assertRaises(RuntimeError):rig.execute('call 1')
        self.assertEqual(rig.owned,set())
    def test_final_report_survives_open_and_cleanup_failure(self):
        with tempfile.TemporaryDirectory() as d:
            class Fake:
                def __init__(self,*a):pass
                def open(self):raise OSError('serial unavailable')
                def cleanup_calls(self):raise OSError('cleanup failed')
                def close(self):pass
            with patch('tools.hardware_test.Rig',Fake):
                self.assertEqual(main(['--output',str(Path(d)/'run')]),1)
            self.assertTrue((Path(d)/'run'/'summary.json').exists())
    def test_real_dispatch_rejects_foreign_reply_then_accepts_matching_ack(self):
        from device_control import DeviceControls
        from protocol import Frame, Node, Command
        with tempfile.TemporaryDirectory() as d:
            report=Report(Path(d)/'results')
            args=arguments(['--call-state-file',str(Path(d)/'calls.json')])
            rig=Rig(args,report)
            class Bus:
                def send_frame(self,request):
                    payload=request.payload[:5]+bytes([0,0])
                    rig.on_frame(Frame(2,Node.P4,Node.PI,request.service,Command.APPLY_RESULT,payload))
                    self.assert_pending()
                    rig.on_frame(Frame(1,Node.P4,Node.PI,request.service,Command.APPLY_RESULT,payload))
                def assert_pending(self):
                    assert rig.controls.result is None
            rig.controls=DeviceControls(Bus(),rig.states,rig.voice,ack_timeout=.01)
            self.assertTrue(rig.step('ping 1'))
            self.assertEqual(rig.rx_control,2)
            self.assertEqual(report.results[0]['status'],'PASS')
            report.close()
    def test_multi_rail_local_audio_rejected(self):
        with self.assertRaises(SystemExit):arguments(['--rails','1,2','--local-audio'])
