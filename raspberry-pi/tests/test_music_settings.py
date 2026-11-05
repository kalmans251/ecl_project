"""Actual settings prefix and legacy firmware compatibility."""
import unittest
from unittest.mock import patch
import music_info


class MusicSettingsTests(unittest.TestCase):
    def test_actual_controls_and_current_filename(self):
        data=b'\x01'+bytes(4)+b'\x05a.mp3'+bytes([37,3])
        with patch('music_info.request',return_value=data):
            self.assertEqual(dict(filename='a.mp3',volume=37,mode='age'),music_info.settings(None,1))

    def test_legacy_does_not_invent_volume_or_mode(self):
        with patch('music_info.request',return_value=b'\x00'+bytes(5)):
            self.assertEqual(dict(filename=None),music_info.settings(None,1))

    def test_invalid_controls_and_lengths_are_rejected(self):
        for data in (b'\x01'+bytes(4)+b'\x00'+bytes([101,3]),
                     b'\x01'+bytes(4)+b'\x00'+bytes([20,0]),
                     b'\x01'+bytes(4)+b'\x05abc'):
            with patch('music_info.request',return_value=data):
                with self.assertRaises(ValueError):music_info.settings(None,1)
