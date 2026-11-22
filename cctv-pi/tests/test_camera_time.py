import asyncio
import base64
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import MagicMock, patch
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import camera_time as clock


def snapshot(moment, zone='KST-9', daylight='false'):
    return ET.fromstring(f'''<s:Envelope xmlns:s="{clock.SOAP}" xmlns:d="{clock.DEVICE}" xmlns:t="{clock.SCHEMA}">
    <s:Body><d:GetSystemDateAndTimeResponse><d:SystemDateAndTime>
    <t:DaylightSavings>{daylight}</t:DaylightSavings><t:TimeZone><t:TZ>{zone}</t:TZ></t:TimeZone>
    <t:UTCDateTime><t:Date><t:Year>{moment.year}</t:Year><t:Month>{moment.month}</t:Month><t:Day>{moment.day}</t:Day></t:Date>
    <t:Time><t:Hour>{moment.hour}</t:Hour><t:Minute>{moment.minute}</t:Minute><t:Second>{moment.second}</t:Second></t:Time>
    </t:UTCDateTime></d:SystemDateAndTime></d:GetSystemDateAndTimeResponse></s:Body></s:Envelope>''')


class ClockTest(unittest.TestCase):
    def setUp(self):
        self.settings = dict(enabled=True, device_url='http://192.168.1.2/onvif/device_service',
                             username='clock-user', password='secret<&')

    def test_opt_in_and_local_endpoint_validation(self):
        clock.validate_config({'camera_url': 'rtsp://192.168.1.2/live'})
        config = dict(camera_url='rtsp://192.168.1.2/live', time_sync=self.settings)
        clock.validate_config(config)
        for url in ('http://other.example/onvif', 'http://user:pass@192.168.1.2/onvif',
                    'http://192.168.1.2/onvif?token=secret', 'ftp://192.168.1.2/onvif'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                clock.validate_config({**config, 'time_sync': {**self.settings, 'device_url': url}})

    def test_pi_must_report_ntp_synchronized(self):
        with patch.object(clock.subprocess, 'run', return_value=MagicMock(stdout='yes\n')):
            self.assertTrue(clock.pi_clock_ready())
        with patch.object(clock.subprocess, 'run', return_value=MagicMock(stdout='no\n')):
            self.assertFalse(clock.pi_clock_ready())
        with patch.object(clock.subprocess, 'run', side_effect=subprocess.TimeoutExpired('timedatectl', 3)):
            self.assertFalse(clock.pi_clock_ready())

    def test_no_camera_request_before_pi_sync(self):
        with patch.object(clock, 'pi_clock_ready', return_value=False), patch.object(clock, 'call') as call:
            self.assertIn('waiting', clock.sync_once(self.settings))
            call.assert_not_called()

    def test_1970_clock_uses_camera_time_for_auth_and_verifies_write(self):
        old = datetime(1970, 1, 1, 17, 46, 3, tzinfo=timezone.utc)
        with patch.object(clock, 'pi_clock_ready', return_value=True), \
                patch.object(clock, 'call', side_effect=[snapshot(old), None, snapshot(datetime.now(timezone.utc))]) as call:
            self.assertIn('synchronized and verified', clock.sync_once(self.settings))
            self.assertEqual([c.args[2] for c in call.call_args_list],
                             ['GetSystemDateAndTime', 'SetSystemDateAndTime', 'GetSystemDateAndTime'])
            write = call.call_args_list[1]
            self.assertEqual(write.kwargs['created'], old)
            self.assertIn('<t:TZ>KST-9</t:TZ>', write.args[3])
            self.assertIn('<t:Year>' + str(datetime.now(timezone.utc).year), write.args[3])

    def test_correct_clock_is_not_rewritten(self):
        with patch.object(clock, 'pi_clock_ready', return_value=True), \
                patch.object(clock, 'call', return_value=snapshot(datetime.now(timezone.utc))) as call:
            self.assertEqual(clock.sync_once(self.settings), 'camera clock verified')
            self.assertEqual(call.call_count, 1)

    def test_write_success_without_clock_change_is_failure(self):
        old = snapshot(datetime(1970, 1, 1, tzinfo=timezone.utc))
        with patch.object(clock, 'pi_clock_ready', return_value=True), \
                patch.object(clock, 'call', side_effect=[old, None, old]), self.assertRaises(ValueError):
            clock.sync_once(self.settings)

    def test_soap_digest_uses_nonce_camera_time_and_password(self):
        nonce = b'x' * 20
        date = datetime(1970, 1, 1, tzinfo=timezone.utc)
        with patch.object(clock.os, 'urandom', return_value=nonce):
            header = clock.security_header('a<&', 'password', date)
        expected = base64.b64encode(hashlib.sha1(nonce + b'1970-01-01T00:00:00Zpassword').digest()).decode()
        self.assertIn(expected, header)
        self.assertIn('a&lt;&amp;', header)
        self.assertNotIn('>password<', header)

    def test_transport_rejects_fault_redirect_and_large_response(self):
        session = MagicMock()
        response = session.post.return_value
        response.status_code = 302
        with self.assertRaises(ValueError):
            clock.call(session, self.settings, 'GetSystemDateAndTime')
        self.assertFalse(session.post.call_args.kwargs['allow_redirects'])
        response.status_code = 200
        response.iter_content.return_value = [b'x' * 65537]
        with self.assertRaises(ValueError):
            clock.call(session, self.settings, 'GetSystemDateAndTime')
        response.iter_content.return_value = [f'<s:Envelope xmlns:s="{clock.SOAP}"><s:Body><s:Fault/></s:Body></s:Envelope>'.encode()]
        with self.assertRaises(ValueError):
            clock.call(session, self.settings, 'GetSystemDateAndTime')

    def test_full_soap_exchange_and_utc_payload(self):
        import requests
        session = MagicMock()
        old = datetime(1970, 1, 1, tzinfo=timezone.utc)
        reply = ET.fromstring(f'<s:Envelope xmlns:s="{clock.SOAP}" xmlns:d="{clock.DEVICE}">'
                              '<s:Body><d:SetSystemDateAndTimeResponse/></s:Body></s:Envelope>')
        responses = []
        for xml in (snapshot(old), reply, snapshot(datetime.now(timezone.utc))):
            response = MagicMock(status_code=200)
            response.iter_content.return_value = [ET.tostring(xml)]
            responses.append(response)
        session.post.side_effect = responses
        with patch.object(requests, 'Session') as factory, \
                patch.object(clock, 'pi_clock_ready', return_value=True):
            factory.return_value.__enter__.return_value = session
            self.assertIn('synchronized and verified', clock.sync_once(self.settings))
        self.assertFalse(session.trust_env)
        write = ET.fromstring(session.post.call_args_list[1].kwargs['data'])
        self.assertEqual(write.findtext('.//d:DateTimeType', namespaces=clock.NS), 'Manual')
        self.assertEqual(write.findtext('.//d:TimeZone/t:TZ', namespaces=clock.NS), 'KST-9')
        self.assertEqual(write.findtext('.//d:DaylightSavings', namespaces=clock.NS), 'false')
        self.assertEqual(write.findtext('.//d:UTCDateTime/t:Time/t:Hour', namespaces=clock.NS),
                         str(datetime.now(timezone.utc).hour))
        for request in session.post.call_args_list:
            self.assertEqual(request.kwargs['timeout'], (3, 3))
            self.assertFalse(request.kwargs['allow_redirects'])


class WorkerTest(unittest.IsolatedAsyncioTestCase):
    async def test_failure_retries_without_leaking_exception_or_stopping_agent(self):
        async def stop(_):
            raise asyncio.CancelledError
        with patch.object(clock, 'sync_once', side_effect=ValueError('SECRET_PASSWORD')), \
                patch.object(clock.asyncio, 'sleep', side_effect=stop), \
                self.assertLogs('camera.time', level='INFO') as logs:
            with self.assertRaises(asyncio.CancelledError):
                await clock.time_sync_loop({'time_sync': {'enabled': True}})
        self.assertIn('time sync failed', str(logs.output))
        self.assertNotIn('SECRET_PASSWORD', str(logs.output))

    async def test_disabled_worker_never_connects(self):
        with patch.object(clock, 'sync_once') as sync:
            await clock.time_sync_loop({})
            sync.assert_not_called()
