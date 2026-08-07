#!/usr/bin/env python3
"""Windows-safe runtime regression tests for disposable E2E execution."""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import e2e_test
import runtime


class TestE2ERuntime(unittest.TestCase):
    @patch('e2e_test.subprocess.run')
    def test_stage_is_unbuffered_and_has_configurable_timeout(self, run):
        e2e_test._run('ingest', 'ingest.py', '--slug', 'sam', env={}, timeout=321)

        command = run.call_args.args[0]
        self.assertEqual(command[1], '-u')
        self.assertEqual(run.call_args.kwargs['timeout'], 321)
        self.assertTrue(run.call_args.kwargs['check'])

    @patch('e2e_test.subprocess.run', side_effect=subprocess.TimeoutExpired(['python'], 2))
    def test_timeout_names_failed_stage(self, _run):
        with self.assertRaisesRegex(RuntimeError, "Stage 'vectors' exceeded 2 seconds"):
            e2e_test._run('vectors', 'ingest.py', env={}, timeout=2)

    def test_cleanup_retries_transient_windows_lock(self):
        root = Path(tempfile.mkdtemp())
        root.joinpath('chroma.sqlite3').write_bytes(b'db')
        real_rmtree = e2e_test.shutil.rmtree
        calls = []

        def flaky(path):
            calls.append(path)
            if len(calls) == 1:
                raise PermissionError('file busy')
            real_rmtree(path)

        with patch('e2e_test.shutil.rmtree', side_effect=flaky), \
                patch('e2e_test.time.sleep'):
            e2e_test._cleanup_with_retries(root)

        self.assertEqual(len(calls), 2)
        self.assertFalse(root.exists())

    def test_safe_output_tolerates_stream_without_reconfigure(self):
        with patch.object(runtime.sys, 'stdout', object()), \
                patch.object(runtime.sys, 'stderr', object()):
            runtime.configure_safe_output()


if __name__ == '__main__':
    unittest.main()
