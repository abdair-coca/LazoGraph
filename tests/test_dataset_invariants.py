#!/usr/bin/env python3
"""Tests for dataset-wide consistency invariants."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import dataset_invariants


class TestDatasetInvariants(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dataset = Path(self.tmp.name) / 'sam'
        self.sources = self.dataset / 'sources'
        self.sources.mkdir(parents=True)
        self.messages = [
            self._message('assistant', 'Sam', 'One.'),
            self._message('user', 'Alex', 'Two.'),
            self._message('assistant', 'Sam', 'Three.'),
        ]
        self.sources.joinpath('chat.jsonl').write_text(
            ''.join(json.dumps(message) + '\n' for message in self.messages),
            encoding='utf-8',
        )
        self._write_participants([2, 1])
        self._write_dataset(total=3, assistant=2, sources=1)

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def _message(role: str, sender: str, content: str) -> dict:
        return {
            'role': role,
            'content': content,
            'metadata': {'sender': sender},
        }

    def _write_participants(self, counts: list[int]):
        payload = {
            'participants': [
                {'name': 'Sam', 'message_count': counts[0]},
                {'name': 'Alex', 'message_count': counts[1]},
            ],
        }
        self.dataset.joinpath('participants.json').write_text(
            json.dumps(payload), encoding='utf-8'
        )

    def _write_dataset(
        self,
        *,
        total: int,
        assistant: int,
        sources: int,
        history: list | None = None,
    ):
        payload = {
            'stats': {
                'sources': sources,
                'total_messages': total,
                'assistant_turns': assistant,
            },
            'export_history': history or [],
        }
        self.dataset.joinpath('dataset.json').write_text(
            json.dumps(payload), encoding='utf-8'
        )

    def test_all_layers_agree(self):
        snapshot = dataset_invariants.build_source_snapshot(self.dataset)
        self._write_dataset(
            total=3,
            assistant=2,
            sources=1,
            history=[{'source_snapshot': snapshot}],
        )
        export_dir = self.dataset / 'export'
        export_dir.mkdir()
        export_dir.joinpath('metadata.json').write_text(
            json.dumps({'source_snapshot': snapshot}), encoding='utf-8'
        )

        result = dataset_invariants.validate_dataset(
            self.dataset,
            vector_count=3,
            export_dir=export_dir,
        )

        self.assertTrue(result['ok'])
        self.assertEqual(result['errors'], [])
        self.assertEqual(result['warnings'], [])
        self.assertEqual(result['counts']['messages'], 3)

    def test_divergent_counts_identify_each_broken_layer(self):
        self._write_dataset(total=9, assistant=8, sources=2)
        self._write_participants([1, 1])

        result = dataset_invariants.validate_dataset(self.dataset, vector_count=2)
        checks = {error['check'] for error in result['errors']}

        self.assertFalse(result['ok'])
        self.assertEqual(checks, {
            'stats.sources',
            'stats.total_messages',
            'stats.assistant_turns',
            'participants.message_count',
            'vectors.count',
        })

    def test_previous_export_difference_is_stale_warning_not_corruption(self):
        self._write_dataset(
            total=3,
            assistant=2,
            sources=1,
            history=[{'source_snapshot': {'old.jsonl': 'sha256:old'}}],
        )

        result = dataset_invariants.validate_dataset(self.dataset, vector_count=3)

        self.assertTrue(result['ok'])
        self.assertEqual(result['warnings'][0]['check'], 'export.latest_snapshot')

    def test_new_export_snapshot_must_match_active_sources(self):
        export_dir = self.dataset / 'export'
        export_dir.mkdir()
        export_dir.joinpath('metadata.json').write_text(
            json.dumps({'source_snapshot': {}}), encoding='utf-8'
        )

        result = dataset_invariants.validate_dataset(
            self.dataset,
            vector_count=3,
            export_dir=export_dir,
        )

        self.assertIn('export.source_snapshot', {
            error['check'] for error in result['errors']
        })


if __name__ == '__main__':
    unittest.main()
