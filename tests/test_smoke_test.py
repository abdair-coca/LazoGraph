#!/usr/bin/env python3
"""Tests for post-rebuild smoke probes."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import smoke_test


class TestSmokeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dataset = Path(self.tmp.name) / 'knowledge' / 'sam'
        self.dataset.mkdir(parents=True)
        self.profiles = [
            {'name': 'Sam', 'aliases': ['Sammy'], 'identity_type': 'persona', 'message_count': 2},
            {'name': 'Alex', 'aliases': ['Al'], 'identity_type': 'contact', 'message_count': 2},
        ]
        self.dataset.joinpath('participants.json').write_text(
            json.dumps({'participants': self.profiles}), encoding='utf-8'
        )
        self.dataset.joinpath('dataset.json').write_text(
            json.dumps({'export_history': []}), encoding='utf-8'
        )
        self.export = Path(self.tmp.name) / 'export'
        self.export.mkdir()
        self.export.joinpath('conversations.jsonl').write_text(
            '\n'.join((
                json.dumps({'role': 'user', 'content': 'Hi'}),
                json.dumps({'role': 'assistant', 'content': 'Hello'}),
            )) + '\n',
            encoding='utf-8',
        )

    def tearDown(self):
        self.tmp.cleanup()

    @patch('smoke_test._wiki', return_value='6 content pages')
    @patch('smoke_test.search_memory')
    @patch('smoke_test._load_kg')
    def test_all_cross_layer_probes_pass(self, load_kg, search_memory, _wiki):
        load_kg.return_value = (
            {'Sam', 'Alex'},
            [{'from': 'Sam', 'to': 'Alex', 'type': 'communicates_with'}],
            None,
        )
        search_memory.side_effect = lambda _dataset, _query, participant, limit: [{
            'metadata': {'sender': participant}, 'content': 'memory',
        }]

        report = smoke_test.run_smoke_tests(self.dataset, export_dir=self.export)

        self.assertTrue(report['ok'])
        self.assertEqual(len(report['checks']), 5)
        self.assertTrue(all(check['status'] == 'passed' for check in report['checks']))

    @patch('smoke_test._wiki', return_value='6 content pages')
    @patch('smoke_test.search_memory', return_value=[])
    @patch('smoke_test._load_kg', return_value=(
        {'Sam', 'Alex'},
        [{'from': 'Sam', 'to': 'Alex', 'type': 'communicates_with'}],
        None,
    ))
    def test_failure_names_broken_layer(self, _load_kg, _search, _wiki):
        report = smoke_test.run_smoke_tests(self.dataset, export_dir=self.export)

        self.assertFalse(report['ok'])
        semantic = next(
            check for check in report['checks']
            if check['name'] == 'participant-semantic-search'
        )
        self.assertEqual(semantic['status'], 'failed')
        self.assertIn('No semantic result', semantic['detail'])

    def test_export_requires_complete_ordered_pairs(self):
        self.export.joinpath('conversations.jsonl').write_text(
            json.dumps({'role': 'assistant', 'content': 'orphan'}) + '\n',
            encoding='utf-8',
        )

        with self.assertRaisesRegex(AssertionError, 'odd turn count'):
            smoke_test._export_pairs(self.dataset, self.export)


if __name__ == '__main__':
    unittest.main()
