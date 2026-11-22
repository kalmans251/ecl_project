import asyncio
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent import Supervisor, ffmpeg_args, load_config

class AgentTest(unittest.IsolatedAsyncioTestCase):
    def config(self):
        return dict(camera_id='cctv01', control_url='wss://example.org/ws/cameras/cctv01',
                    control_token='a'*43, publish_token='b'*43, camera_url='rtsp://user:secret@192.168.1.2/1/2',
                    server_host='example.org', srt_passphrase='c'*43)
    def desired(self, **extra):
        return dict(version=1, type='desired', camera_id='cctv01', revision='12345678-1234-1234-1234-123456789abc', stream=True, lease_seconds=15, **extra)
    def test_fixed_command_and_validation(self):
        args=ffmpeg_args(self.config())
        self.assertIn('copy',args);self.assertIn('-an',args)
        self.assertIn('passphrase=',args[-1]);self.assertIn('publish%3Acctv01_raw',args[-1])
        s=Supervisor(self.config())
        with self.assertRaises(ValueError):s.desired(self.desired(command='rm -rf /'))
        msg=self.desired();msg['camera_id']='other'
        with self.assertRaises(ValueError):s.desired(msg)
        msg=self.desired();msg['lease_seconds']=1000
        with self.assertRaises(ValueError):s.desired(msg)
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'c.json';p.write_text(json.dumps(self.config()));p.chmod(0o600)
            self.assertEqual(load_config(p)['camera_id'],'cctv01')
            c=self.config();c['control_url']='ws://example.org/ws/cameras/cctv01';p.write_text(json.dumps(c))
            with self.assertRaises(ValueError):load_config(p)
    async def test_expiry_and_stop_do_not_spawn(self):
        now=[10.0];s=Supervisor(self.config(),lambda:now[0]);s.stop=AsyncMock()
        s.desired(self.desired());now[0]=26
        with patch('asyncio.create_subprocess_exec',new_callable=AsyncMock) as spawn:
            await s.tick();s.stop.assert_awaited_once();spawn.assert_not_awaited()
        s.desired(self.desired());s.wanted=False
        with patch('asyncio.create_subprocess_exec',new_callable=AsyncMock) as spawn:
            await s.tick();spawn.assert_not_awaited()
    async def test_progress_required_for_streaming(self):
        s=Supervisor(self.config(),lambda:7)
        class Proc:pass
        p=Proc();p.stdout=asyncio.StreamReader();p.stdout.feed_data(b'out_time_us=100\nout_time_us=100\n');p.stdout.feed_eof()
        await s.progress(p);self.assertEqual(s.state,'streaming');self.assertEqual(s.last_progress,7)


class RtspCompatibilityTest(unittest.TestCase):
    def test_modern_and_legacy_timeout_units(self):
        from agent import rtsp_timeout_option
        from types import SimpleNamespace
        for help_text, expected in [
            ('  -timeout <int64> set timeout (in microseconds) of socket I/O operations', '-timeout'),
            ('  -timeout <int> wait for incoming connections (seconds)\n  -stimeout <int> TCP socket I/O timeout', '-stimeout'),
            ('  -timeout <int> wait for incoming connections (seconds)', None),
            ('no supported timeout', None),
        ]:
            with self.subTest(expected=expected), patch('agent.subprocess.run', return_value=SimpleNamespace(stdout=help_text)):
                self.assertEqual(rtsp_timeout_option(), expected)

    def test_help_probe_failure_uses_watchdog(self):
        import subprocess
        from agent import rtsp_timeout_option
        for error in (OSError('not installed'), subprocess.TimeoutExpired('ffmpeg', 3)):
            with patch('agent.subprocess.run', side_effect=error):
                self.assertIsNone(rtsp_timeout_option())

    def test_generated_command_uses_only_supported_option_before_input(self):
        config=AgentTest().config()
        for option in ('-timeout', '-stimeout', None):
            args=ffmpeg_args(config, option)
            self.assertNotIn('-rw_timeout', args)
            if option:
                self.assertLess(args.index(option), args.index('-i'))
                self.assertEqual(args[args.index(option)+1], '10000000')
            else:
                self.assertNotIn('-timeout', args);self.assertNotIn('-stimeout', args)
        with self.assertRaises(ValueError):ffmpeg_args(config, '-rw_timeout')

    def test_installed_ffmpeg_accepts_selected_input_option(self):
        import shutil, subprocess
        from agent import rtsp_timeout_option
        if not shutil.which('ffmpeg'):self.skipTest('FFmpeg not installed')
        option=rtsp_timeout_option()
        args=['ffmpeg','-nostdin','-hide_banner','-loglevel','error','-rtsp_transport','tcp']
        if option:args += [option,'1000000']
        args += ['-i','rtsp://127.0.0.1:1/test','-frames:v','1','-f','null','-']
        result=subprocess.run(args,capture_output=True,text=True,timeout=5)
        self.assertNotIn('Option not found',result.stderr)
        self.assertNotIn('Unrecognized option',result.stderr)
        self.assertIn('Connection refused',result.stderr)

if __name__=='__main__':unittest.main()
