#!/usr/bin/env python3
"""Tests for recoverable duplicate-source reconciliation."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import reconcile_sources


class TestReconcileSources(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dataset = Path(self.tmp.name) / 'sam'
        self.sources = self.dataset / 'sources'
        self.sources.mkdir(parents=True)
        self.dataset.joinpath('dataset.json').write_text(json.dumps({
            'name': 'Sam',
            'stats': {'sources': 2, 'total_messages': 3, 'assistant_turns': 2},
        }), encoding='utf-8')
        self.sources.joinpath('.source-index.json').write_text(json.dumps({
            'files': [
                {'filename': 'official.jsonl'},
                {'filename': 'duplicate.jsonl'},
            ],
            'last_updated': '',
        }), encoding='utf-8')
        official = [
            self._message('assistant', 'Sam', 'Hello.'),
            self._message('user', 'Alex', 'Hi.'),
        ]
        duplicate = [
            *official,
            self._message('user', 'System notice', 'Bad extra.'),
        ]
        self._write_jsonl('official.jsonl', official)
        self._write_jsonl('duplicate.jsonl', duplicate)

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def _message(role, sender, content):
        return {
            'role': role,
            'content': content,
            'metadata': {'sender': sender},
        }

    def _write_jsonl(self, name, messages):
        self.sources.joinpath(name).write_text(
            ''.join(json.dumps(message) + '\n' for message in messages),
            encoding='utf-8',
        )

    def test_dry_run_reports_without_moving(self):
        result = reconcile_sources.reconcile_sources(
            self.dataset, 'official.jsonl', apply=False
        )

        self.assertEqual(result['messages'], 2)
        self.assertEqual(result['quarantined'], ['duplicate.jsonl'])
        self.assertTrue(self.sources.joinpath('duplicate.jsonl').exists())

    def test_apply_quarantines_duplicate_and_reconciles_metadata(self):
        result = reconcile_sources.reconcile_sources(
            self.dataset, 'official.jsonl', apply=True
        )

        self.assertFalse(self.sources.joinpath('duplicate.jsonl').exists())
        quarantine = Path(result['quarantine_dir'])
        self.assertTrue(quarantine.joinpath('duplicate.jsonl').exists())
        self.assertTrue(quarantine.joinpath('reconciliation.json').exists())
        metadata = json.loads(self.dataset.joinpath('dataset.json').read_text(encoding='utf-8'))
        self.assertEqual(metadata['stats']['sources'], 1)
        self.assertEqual(metadata['stats']['total_messages'], 2)
        self.assertEqual(metadata['stats']['assistant_turns'], 1)
        profiles = json.loads(
            self.dataset.joinpath('participants.json').read_text(encoding='utf-8')
        )['participants']
        self.assertEqual([profile['name'] for profile in profiles], ['Alex', 'Sam'])
        source_index = json.loads(
            self.sources.joinpath('.source-index.json').read_text(encoding='utf-8')
        )
        self.assertEqual(source_index['files'], [{'filename': 'official.jsonl'}])
        self.assertEqual(len(source_index['quarantine_history']), 1)

    def test_apply_with_no_candidates_is_safe_no_op(self):
        self.sources.joinpath('duplicate.jsonl').unlink()

        result = reconcile_sources.reconcile_sources(
            self.dataset, 'official.jsonl', apply=True
        )

        self.assertEqual(result['quarantined'], [])
        self.assertIsNone(result['quarantine_dir'])
        self.assertTrue(self.sources.joinpath('official.jsonl').exists())


if __name__ == '__main__':
    unittest.main()
