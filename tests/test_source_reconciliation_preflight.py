#!/usr/bin/env python3
"""Tests for confirmed equivalent-source replacement and selective quarantine."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import ingest


class TestSourceReconciliationPreflight(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dataset = Path(self.tmp.name) / 'sam'
        self.sources = self.dataset / 'sources'
        self.sources.mkdir(parents=True)
        self.official = [self._message(index) for index in range(25)]
        self.unrelated = [self._message(index) for index in range(100, 102)]
        self._write_jsonl('official.jsonl', self.official)
        self._write_jsonl('unrelated.jsonl', self.unrelated)
        self.sources.joinpath('.source-index.json').write_text(json.dumps({
            'files': [
                {'filename': 'official.jsonl'},
                {'filename': 'unrelated.jsonl'},
            ],
            'last_updated': '',
        }), encoding='utf-8')
        self.dataset.joinpath('dataset.json').write_text(json.dumps({
            'slug': 'sam',
            'name': 'Sam',
            'stats': {
                'sources': 2,
                'total_messages': 27,
                'assistant_turns': 27,
                'kg_entities': 0,
                'kg_relationships': 0,
            },
        }), encoding='utf-8')

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def _message(index: int) -> dict:
        return {
            'role': 'assistant',
            'content': f'Message {index}.',
            'timestamp': f'2026-01-01T00:{index % 60:02d}:00',
            'source_file': 'candidate.txt',
            'source_type': 'whatsapp',
            'metadata': {'sender': 'Sam'},
        }

    def _write_jsonl(self, filename: str, messages: list[dict]):
        self.sources.joinpath(filename).write_text(
            ''.join(json.dumps(message) + '\n' for message in messages),
            encoding='utf-8',
        )

    @staticmethod
    def _valid_invariants() -> dict:
        return {
            'ok': True,
            'errors': [],
            'warnings': [],
            'counts': {
                'source_files': 2,
                'messages': 27,
                'assistant_turns': 27,
                'participant_messages': 27,
                'vectors': 27,
            },
            'source_snapshot': {},
        }

    def test_confirmed_replacement_quarantines_only_match_and_rebuilds_layers(self):
        matches = [{'filename': 'official.jsonl'}]
        with (
            patch.object(ingest, '_prune_mempalace', return_value=1),
            patch.object(ingest, '_store_in_mempalace', return_value=27) as store,
            patch.object(ingest, '_clear_managed_kg', return_value=4),
            patch.object(ingest, '_prune_invalid_kg_entities', return_value=0),
            patch.object(
                ingest,
                '_extract_kg_triples',
                return_value={'entities': 3, 'relationships': 2},
            ),
            patch.object(ingest, 'validate_dataset', return_value=self._valid_invariants()),
            patch.object(ingest, 'print_invariant_report', return_value=True),
        ):
            result = ingest._run_equivalent_source_reconciliation(
                self.dataset,
                'sam',
                self.official,
                matches,
                'chat_export',
                'candidate.txt',
                set(),
            )

        self.assertFalse(self.sources.joinpath('official.jsonl').exists())
        self.assertTrue(self.sources.joinpath('unrelated.jsonl').exists())
        quarantine = Path(result['quarantine']['quarantine_dir'])
        self.assertTrue(quarantine.joinpath('official.jsonl').exists())
        manifest = json.loads(quarantine.joinpath('reconciliation.json').read_text())
        self.assertEqual(manifest['reason'], 'equivalent-source-preflight')
        self.assertEqual(manifest['quarantined'], ['official.jsonl'])

        active_sources = sorted(path.name for path in self.sources.glob('*.jsonl'))
        self.assertEqual(len(active_sources), 2)
        self.assertIn('unrelated.jsonl', active_sources)
        self.assertNotIn('official.jsonl', active_sources)
        stored_messages = store.call_args.args[2]
        self.assertEqual(len(stored_messages), 27)

        stats = json.loads(self.dataset.joinpath('dataset.json').read_text())['stats']
        self.assertEqual(stats['sources'], 2)
        self.assertEqual(stats['total_messages'], 27)
        self.assertEqual(stats['assistant_turns'], 27)
        self.assertEqual(stats['kg_entities'], 3)
        self.assertEqual(stats['kg_relationships'], 2)

        source_index = json.loads(self.sources.joinpath('.source-index.json').read_text())
        indexed = {entry['filename'] for entry in source_index['files']}
        self.assertEqual(indexed, set(active_sources))
        self.assertEqual(source_index['quarantine_history'][-1]['files'], ['official.jsonl'])


if __name__ == '__main__':
    unittest.main()
