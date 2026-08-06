#!/usr/bin/env python3
"""Tests for equivalent-source detection before ingestion writes."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import ingest


class TestSourceEquivalence(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.dataset = self.root / 'sam'
        self.sources = self.dataset / 'sources'
        self.sources.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def _message(index: int, *, role: str = 'assistant') -> dict:
        return {
            'role': role,
            'content': f'Unique message number {index}.',
            'metadata': {'sender': 'Sam' if role == 'assistant' else 'Alex'},
        }

    @staticmethod
    def _write_jsonl(path: Path, messages: list[dict]):
        path.write_text(
            ''.join(json.dumps(message) + '\n' for message in messages),
            encoding='utf-8',
        )

    def test_near_identical_large_backup_is_detected_across_role_changes(self):
        existing = [self._message(index) for index in range(100)]
        candidate = [
            self._message(index, role='user' if index % 2 else 'assistant')
            for index in range(98)
        ] + [self._message(100), self._message(101)]
        self._write_jsonl(self.sources / 'official.jsonl', existing)

        matches = ingest._find_equivalent_sources(self.dataset, candidate)

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]['filename'], 'official.jsonl')
        self.assertEqual(matches[0]['overlap'], 98)
        self.assertEqual(matches[0]['coverage'], 0.98)

    def test_real_e2e_source_counts_are_classified_as_equivalent(self):
        existing = [self._message(index) for index in range(3614)]
        candidate = [self._message(index) for index in range(3578)] + [
            self._message(index) for index in range(10_000, 10_049)
        ]
        self._write_jsonl(self.sources / 'direct-export.jsonl', existing)

        matches = ingest._find_equivalent_sources(self.dataset, candidate)

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]['candidate_messages'], 3627)
        self.assertEqual(matches[0]['existing_messages'], 3614)
        self.assertEqual(matches[0]['overlap'], 3578)

    def test_different_large_source_is_not_detected(self):
        self._write_jsonl(
            self.sources / 'official.jsonl',
            [self._message(index) for index in range(100)],
        )
        candidate = [self._message(index) for index in range(200, 300)]

        self.assertEqual(ingest._find_equivalent_sources(self.dataset, candidate), [])

    def test_small_sources_must_be_exactly_identical(self):
        existing = [self._message(index) for index in range(3)]
        self._write_jsonl(self.sources / 'official.jsonl', existing)

        exact = ingest._find_equivalent_sources(self.dataset, list(existing))
        partial = ingest._find_equivalent_sources(
            self.dataset,
            [*existing, self._message(4)],
        )

        self.assertEqual(len(exact), 1)
        self.assertEqual(partial, [])

    def test_cli_stops_before_storage_when_equivalent_source_exists(self):
        existing = [self._message(index) for index in range(25)]
        self._write_jsonl(self.sources / 'official.jsonl', existing)
        candidate_path = self.root / 'candidate.jsonl'

        argv = [
            'ingest.py',
            '--slug', 'sam',
            '--source', str(candidate_path),
            '--adapter', 'universal',
            '--persona-name', 'Sam',
        ]
        with (
            patch.object(ingest, 'KNOWLEDGE_ROOT', self.root),
            patch.object(sys, 'argv', argv),
            patch.object(
                ingest,
                '_load_adapter',
                return_value=SimpleNamespace(parse=lambda *_args, **_kwargs: list(existing)),
            ),
            patch.object(ingest, '_store_in_mempalace') as store,
            self.assertRaises(SystemExit) as raised,
        ):
            ingest.main()

        self.assertEqual(raised.exception.code, 2)
        store.assert_not_called()
        self.assertEqual(list(self.sources.glob('*.jsonl')), [self.sources / 'official.jsonl'])


if __name__ == '__main__':
    unittest.main()
