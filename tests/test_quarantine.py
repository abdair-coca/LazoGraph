#!/usr/bin/env python3
"""Tests for structured quarantine inspection and transactional restoration."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import quarantine


class TestQuarantine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dataset = Path(self.tmp.name) / 'sam'
        self.sources = self.dataset / 'sources'
        self.batch = self.sources / 'quarantine' / '20260807T120000Z'
        self.batch.mkdir(parents=True)
        message = {'role': 'assistant', 'content': 'Hello', 'metadata': {'sender': 'Sam'}}
        self.batch.joinpath('old.jsonl').write_text(json.dumps(message) + '\n', encoding='utf-8')
        self.batch.joinpath('reconciliation.json').write_text(json.dumps({
            'applied_at': '2026-08-07T12:00:00+00:00',
            'reason': 'manual-source-reconciliation',
            'quarantined': ['old.jsonl'],
        }), encoding='utf-8')
        self.batch.joinpath('source-index-20260807T120000Z.json').write_text(json.dumps({
            'files': [{'filename': 'old.jsonl', 'adapter': 'chat_export', 'lines': 1}],
        }), encoding='utf-8')
        self.sources.joinpath('.source-index.json').write_text(
            json.dumps({'files': []}), encoding='utf-8'
        )
        self.dataset.joinpath('dataset.json').write_text(
            json.dumps({'slug': 'sam', 'stats': {}}), encoding='utf-8'
        )
        palace = self.dataset / '.mempalace' / 'palace'
        palace.mkdir(parents=True)
        palace.joinpath('state.bin').write_bytes(b'old')
        self.dataset.joinpath('participants.json').write_text('{}', encoding='utf-8')
        self.dataset.joinpath('wiki').mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_list_and_show_include_manifest_hash_and_counts(self):
        batches = quarantine.list_batches(self.dataset)

        self.assertEqual(len(batches), 1)
        self.assertEqual(batches[0]['status'], 'available')
        self.assertEqual(batches[0]['files'][0]['filename'], 'old.jsonl')
        self.assertEqual(batches[0]['files'][0]['lines'], 1)
        self.assertEqual(len(batches[0]['files'][0]['sha256']), 64)

    def test_restore_defaults_to_non_mutating_plan(self):
        result = quarantine.restore_batch(self.dataset, self.batch.name)

        self.assertFalse(result['apply'])
        self.assertTrue(self.batch.joinpath('old.jsonl').exists())
        self.assertFalse(self.sources.joinpath('old.jsonl').exists())

    @patch('quarantine._rebuild_derived_layers', return_value={
        'messages': 1, 'vectors_stored': 1, 'invariants': {'ok': True},
    })
    def test_apply_restores_source_index_and_records_success(self, _rebuild):
        result = quarantine.restore_batch(self.dataset, self.batch.name, apply=True)

        self.assertTrue(result['apply'])
        self.assertTrue(self.sources.joinpath('old.jsonl').exists())
        self.assertFalse(self.batch.joinpath('old.jsonl').exists())
        self.assertTrue(self.batch.joinpath('restoration.json').exists())
        index = json.loads(self.sources.joinpath('.source-index.json').read_text(encoding='utf-8'))
        self.assertEqual(index['files'][0]['adapter'], 'chat_export')
        self.assertEqual(index['restore_history'][0]['files'], ['old.jsonl'])

    @patch('quarantine._rebuild_derived_layers', side_effect=RuntimeError('rebuild failed'))
    def test_failed_rebuild_rolls_source_and_derived_state_back(self, _rebuild):
        with self.assertRaisesRegex(RuntimeError, 'rebuild failed'):
            quarantine.restore_batch(self.dataset, self.batch.name, apply=True)

        self.assertTrue(self.batch.joinpath('old.jsonl').exists())
        self.assertFalse(self.sources.joinpath('old.jsonl').exists())
        self.assertEqual(
            self.dataset.joinpath('.mempalace', 'palace', 'state.bin').read_bytes(),
            b'old',
        )
        index = json.loads(self.sources.joinpath('.source-index.json').read_text(encoding='utf-8'))
        self.assertEqual(index['files'], [])

    def test_restore_refuses_active_filename_conflict(self):
        self.sources.joinpath('old.jsonl').write_text('active', encoding='utf-8')

        with self.assertRaisesRegex(RuntimeError, 'conflicts'):
            quarantine.restore_batch(self.dataset, self.batch.name, apply=True)


if __name__ == '__main__':
    unittest.main()
