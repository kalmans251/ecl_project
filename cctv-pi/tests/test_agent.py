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

if __name__=='__main__':unittest.main()
