#!/usr/bin/env python3
"""Tests for export PII block, redact, and explicit allow policies."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / 'scripts' / 'export_training.py'
sys.path.insert(0, str(ROOT / 'scripts'))

import pii


class TestPIIPolicy(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / 'knowledge'
        self.dataset = self.root / 'sam'
        sources = self.dataset / 'sources'
        wiki = self.dataset / 'wiki'
        sources.mkdir(parents=True)
        wiki.mkdir()
        messages = [
            {'role': 'user', 'content': 'Email me at alex@example.com'},
            {'role': 'assistant', 'content': 'Call 555-123-4567 tomorrow'},
        ]
        sources.joinpath('chat.jsonl').write_text(
            ''.join(json.dumps(item) + '\n' for item in messages), encoding='utf-8'
        )
        wiki.joinpath('identity.md').write_text(
            '# Identity\n\n## Content\n\nContact alex@example.com for a detailed response.',
            encoding='utf-8',
        )
        self.dataset.joinpath('dataset.json').write_text(json.dumps({
            'schema_version': 1,
            'slug': 'sam',
            'name': 'Sam',
            'stats': {'sources': 1, 'total_messages': 2, 'assistant_turns': 1},
            'export_history': [],
        }), encoding='utf-8')

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, output: Path, policy: str | None = None):
        env = os.environ.copy()
        env['OPENPERSONA_KNOWLEDGE'] = str(self.root)
        command = [sys.executable, str(SCRIPT), '--slug', 'sam', '--output', str(output)]
        if policy:
            command.extend(['--pii-policy', policy])
        return subprocess.run(command, env=env, capture_output=True, text=True)

    def test_redactor_replaces_every_supported_type(self):
        text = 'a@b.com 555-123-4567 123-45-6789 password=secret 1111 2222 3333 4444'

        redacted, counts = pii.redact_text(text)

        self.assertNotIn('a@b.com', redacted)
        self.assertIn('[REDACTED_EMAIL]', redacted)
        self.assertEqual(set(counts), {'SSN', 'credit_card', 'email', 'password', 'phone'})

    def test_default_block_stops_before_output_creation(self):
        output = Path(self.tmp.name) / 'blocked'

        result = self._run(output)

        self.assertEqual(result.returncode, 2)
        self.assertIn('PII policy blocked export', result.stderr)
        self.assertFalse(output.exists())
        metadata = json.loads(self.dataset.joinpath('dataset.json').read_text(encoding='utf-8'))
        self.assertEqual(metadata['export_history'], [])

    def test_redact_removes_pii_from_every_content_artifact(self):
        output = Path(self.tmp.name) / 'redacted'

        result = self._run(output, 'redact')

        self.assertEqual(result.returncode, 0, result.stderr)
        for path in (
            output / 'raw' / 'chat.jsonl',
            output / 'conversations.jsonl',
            output / 'profile.md',
            output / 'probes.json',
        ):
            content = path.read_text(encoding='utf-8')
            self.assertNotIn('alex@example.com', content)
            self.assertNotIn('555-123-4567', content)
        export_meta = json.loads(output.joinpath('metadata.json').read_text(encoding='utf-8'))
        self.assertEqual(export_meta['pii']['policy'], 'redact')
        self.assertGreater(export_meta['pii']['redacted']['email'], 0)
        self.assertNotIn(str(self.dataset), export_meta['source'])

    def test_allow_is_explicit_and_preserves_original(self):
        output = Path(self.tmp.name) / 'allowed'

        result = self._run(output, 'allow')

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('alex@example.com', output.joinpath('raw', 'chat.jsonl').read_text())
        export_meta = json.loads(output.joinpath('metadata.json').read_text(encoding='utf-8'))
        self.assertEqual(export_meta['pii']['policy'], 'allow')


if __name__ == '__main__':
    unittest.main()
