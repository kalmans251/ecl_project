"""Keep the CI runner fail-closed if discovery changes or a test starts skipping."""
import contextlib
import io
import unittest
from unittest.mock import patch

import run_host_tests


class HostRunnerTests(unittest.TestCase):
    def check_result(self, outcome):
        class Example(unittest.TestCase):
            def runTest(self):
                if outcome == 'skip':
                    self.skipTest('dependency absent')
                if outcome == 'fail':
                    self.fail('bad PCM')
        test = Example()
        suite = unittest.TestSuite([test])
        with patch.object(run_host_tests.unittest.defaultTestLoader, 'discover', return_value=suite), \
             patch.object(run_host_tests, 'REQUIRED', {test.id()}), \
             contextlib.redirect_stderr(io.StringIO()):
            return run_host_tests.run_tests()

    def test_success(self):
        self.assertEqual(self.check_result('pass'), 0)

    def test_failed_decode_fails_job(self):
        self.assertEqual(self.check_result('fail'), 1)

    def test_skip_fails_job(self):
        self.assertEqual(self.check_result('skip'), 1)

    def test_missing_required_test_fails_job(self):
        with patch.object(run_host_tests.unittest.defaultTestLoader, 'discover',
                          return_value=unittest.TestSuite()):
            with self.assertRaisesRegex(RuntimeError, 'Required tests not discovered'):
                run_host_tests.run_tests()
