import json
import tempfile
import threading
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from music_remote import MusicRemote
from music_info import page, play, request
from device_control import DeviceControls
from protocol import Command
from railing import RailingManager
from voice import VoiceRelay
from test_music_info import Bus

class MusicRemoteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.bus = Bus(); self.bus.transaction = threading.RLock
        rails = RailingManager()
        self.controls = DeviceControls(self.bus, rails, VoiceRelay(self.bus, rails), ack_timeout=.01)
        self.bus.controls = self.controls
        self.journal = self.temp.name+'/music.sqlite3'
        self.remote = MusicRemote(self.controls, [1], self.journal)
    def command(self, operation='music.list', value='default:0'):
        return dict(version=1,type='command',message_id=str(uuid.uuid4()),railing_id=1,
                    operation=operation,value=value,expires_at=(datetime.now(timezone.utc)+timedelta(seconds=14)).isoformat())
    def test_page_then_selected_track_is_confirmed_and_not_replayed_after_restart(self):
        result = self.remote.handle(self.command())
        self.assertEqual(result['status'], 'COMPLETED')
        self.assertEqual(result['data']['tracks'][0]['filename'], 'a.mp3')
        command = self.command('music.play', '5:default:0')
        result = self.remote.handle(command)
        self.assertEqual(result['status'], 'APPLIED')
        sent = len(self.bus.sent)
        restarted = MusicRemote(self.controls, [1], self.journal)
        self.assertEqual(restarted.handle(command), result)
        self.assertEqual(len(self.bus.sent), sent)
        self.assertEqual(restarted.handle(dict(command,value='6:default:0'))['status'], 'FAILED')
    def test_unknown_write_is_never_replayed(self):
        command = self.command('music.play', '5:default:0')
        with patch('music_remote.play', side_effect=TimeoutError()) as send:
            self.assertEqual(self.remote.handle(command)['status'], 'UNKNOWN')
            self.assertEqual(self.remote.handle(command)['status'], 'UNKNOWN')
            send.assert_called_once()
    def test_expired_wrong_rail_or_disconnected_never_transmits(self):
        expired = self.command();expired['expires_at']=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
        self.assertEqual(self.remote.handle(expired)['status'], 'EXPIRED')
        self.assertEqual(self.remote.handle(dict(self.command(),railing_id=2))['status'], 'FAILED')
        self.assertEqual(self.remote.handle(self.command(),connected=lambda:False)['status'], 'UNKNOWN')
        self.assertEqual(self.bus.sent, [])
    def test_guard_is_checked_after_acquiring_transaction_and_between_page_reads(self):
        def abort(): raise TimeoutError()
        with self.assertRaises(TimeoutError): request(self.controls,1,Command.MUSIC_INFO,guard=abort)
        self.assertEqual(self.bus.sent, [])
        with patch('music_info.request', wraps=request) as send:
            calls = 0
            def cancel():
                nonlocal calls
                calls += 1
                if calls>1: raise TimeoutError()
            with self.assertRaises(TimeoutError): page(self.controls,1,'default',guard=cancel)
        self.assertEqual(len(self.bus.sent), 1)
        self.assertNotIn(1,self.controls.music_catalogs)
    def test_changed_version_and_unlisted_track_cannot_play(self):
        page(self.controls,1,'default')
        before=len(self.bus.sent)
        with self.assertRaises(ValueError): play(self.controls,1,'default','0',expected_version=6)
        with self.assertRaises(ValueError): play(self.controls,1,'default','1',expected_version=5)
        self.assertEqual(len(self.bus.sent),before)
    def test_busy_command_is_not_queued(self):
        self.remote.lock.acquire()
        try:self.assertEqual(self.remote.handle(self.command())['status'],'BUSY')
        finally:self.remote.lock.release()
        self.assertEqual(self.bus.sent,[])
    def test_crash_pending_journal_cannot_reexecute(self):
        import hashlib
        import sqlite3
        command = self.command('music.play','5:default:0')
        fingerprint = hashlib.sha256(json.dumps([1,'music.play','5:default:0',command['expires_at']]).encode()).hexdigest()
        with sqlite3.connect(self.journal) as db:
            db.execute('INSERT INTO requests VALUES(?,?,?,NULL)',(command['message_id'],fingerprint,datetime.fromisoformat(command['expires_at']).timestamp()))
        self.assertEqual(self.remote.handle(command)['status'],'UNKNOWN')
        self.assertEqual(self.bus.sent,[])
    def test_catalog_pages_are_bounded_and_sd_change_discards_old_selection(self):
        version = 5
        def reply(controls, rail, op, payload=b'', **kwargs):
            if op == Command.MUSIC_CATALOG:
                return version.to_bytes(4,'big') + (32).to_bytes(2,'big') + bytes(8)
            return payload + b'\x05a.mp3'
        with patch('music_info.request',side_effect=reply) as send:
            first=page(self.controls,1,'default',0)
            self.assertEqual(len(first['tracks']),8)
            self.assertEqual(send.call_count,10)  # catalog + eight names + catalog recheck
            page(self.controls,1,'default',8)
            self.assertEqual(len(self.controls.music_catalogs[1]['tracks']),16)
            version=6
            page(self.controls,1,'default',8)
        self.assertEqual(len(self.controls.music_catalogs[1]['tracks']),8)
        with self.assertRaises(ValueError):play(self.controls,1,'default','0',expected_version=6)
