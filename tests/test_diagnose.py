#!/usr/bin/env python3
"""Tests for the read-only dataset diagnostic command."""

import hashlib
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import diagnose
from dataset_invariants import build_source_snapshot


class TestDiagnose(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.knowledge = self.base / 'knowledge'
        self.dataset = self.knowledge / 'sam'
        self.sources = self.dataset / 'sources'
        self.sources.mkdir(parents=True)
        self.messages = [
            self._message('assistant', 'Sam', 'Project update.'),
            self._message('user', 'Alex', 'How is it going?'),
        ]
        self.sources.joinpath('chat.jsonl').write_text(
            ''.join(json.dumps(item) + '\n' for item in self.messages),
            encoding='utf-8',
        )
        self.dataset.joinpath('participants.json').write_text(json.dumps({
            'participants': [
                {
                    'name': 'Sam', 'identity_type': 'persona', 'message_count': 1,
                    'assistant_messages': 1, 'user_messages': 0,
                },
                {
                    'name': 'Alex', 'identity_type': 'contact', 'message_count': 1,
                    'assistant_messages': 0, 'user_messages': 1,
                },
            ],
        }), encoding='utf-8')
        self._create_vector_db()
        self._create_kg_db()
        self._create_wiki()
        self._create_export()

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def _message(role: str, sender: str, content: str) -> dict:
        return {'role': role, 'content': content, 'metadata': {'sender': sender}}

    def _create_vector_db(self):
        path = self.dataset / '.mempalace' / 'palace' / 'chroma.sqlite3'
        path.parent.mkdir(parents=True)
        connection = sqlite3.connect(path)
        connection.execute('CREATE TABLE embeddings (id INTEGER PRIMARY KEY)')
        connection.executemany('INSERT INTO embeddings VALUES (?)', [(1,), (2,)])
        connection.commit()
        connection.close()

    def _create_kg_db(self):
        path = self.dataset / '.mempalace' / 'palace' / 'knowledge_graph.sqlite3'
        connection = sqlite3.connect(path)
        connection.execute('CREATE TABLE entities (id TEXT PRIMARY KEY, name TEXT)')
        connection.executemany('INSERT INTO entities VALUES (?, ?)', [('1', 'Sam'), ('2', 'Alex')])
        connection.execute(
            'CREATE TABLE triples ('
            'subject TEXT, predicate TEXT, object TEXT, confidence REAL, '
            'source_file TEXT, valid_from TEXT)'
        )
        connection.execute(
            'INSERT INTO triples VALUES (?, ?, ?, ?, ?, ?)',
            ('1', 'communicates_with', '2', 1.0, 'chat.jsonl', None),
        )
        connection.commit()
        connection.close()

    def _create_wiki(self):
        wiki = self.dataset / 'wiki'
        wiki.mkdir()
        wiki.joinpath('identity.md').write_text(
            '# Identity\n\n' + ('Evidence [L1:chat] ' * 8) + '\n\nchat.jsonl',
            encoding='utf-8',
        )
        wiki.joinpath('_changelog.md').write_text(
            '# Changelog\n\n| Date | Action |\n|---|---|\n| now | built |\n',
            encoding='utf-8',
        )

    def _create_export(self):
        snapshot = build_source_snapshot(self.dataset)
        export_dir = self.base / 'exports' / 'sam-final'
        export_dir.mkdir(parents=True)
        export_dir.joinpath('raw').mkdir()
        conversations = b'{"messages": []}\n'
        export_dir.joinpath('conversations.jsonl').write_bytes(conversations)
        export_dir.joinpath('profile.md').write_text('# Sam', encoding='utf-8')
        export_dir.joinpath('probes.json').write_text('[]', encoding='utf-8')
        export_hash = 'sha256:' + hashlib.sha256(conversations).hexdigest()[:16]
        export_dir.joinpath('metadata.json').write_text(json.dumps({
            'slug': 'sam',
            'export_version': 'v1',
            'export_hash': export_hash,
            'source_snapshot': snapshot,
        }), encoding='utf-8')
        self.dataset.joinpath('dataset.json').write_text(json.dumps({
            'slug': 'sam',
            'name': 'Sam',
            'schema_version': 1,
            'stats': {'sources': 1, 'total_messages': 2, 'assistant_turns': 1},
            'export_history': [{
                'version': 'v1',
                'exported_at': '2026-08-07T00:00:00+00:00',
                'export_hash': export_hash,
                'source_snapshot': snapshot,
                'conversation_count': 1,
            }],
        }), encoding='utf-8')

    @patch('diagnose._git_info', return_value={
        'commit': 'abc1234', 'branch': 'main', 'dirty': False,
    })
    def test_collects_every_persisted_layer(self, _git):
        report = diagnose.build_diagnosis(self.dataset, repo_root=ROOT)

        self.assertTrue(report['ok'])
        self.assertEqual(report['sources']['messages'], 2)
        self.assertEqual(report['participants']['identity_types'], {'contact': 1, 'persona': 1})
        self.assertEqual(report['vectors']['count'], 2)
        self.assertEqual(report['kg']['entities'], 2)
        self.assertEqual(report['kg']['relationships'], 1)
        self.assertEqual(report['wiki']['status'], 'healthy')
        self.assertEqual(report['export']['status'], 'healthy')
        self.assertEqual(report['schema_version'], 1)

    @patch('diagnose._git_info', return_value={
        'commit': 'abc1234', 'branch': 'main', 'dirty': False,
    })
    def test_stale_export_is_visible_without_marking_dataset_corrupt(self, _git):
        payload = json.loads(self.dataset.joinpath('dataset.json').read_text(encoding='utf-8'))
        payload['export_history'][-1]['source_snapshot'] = {'old.jsonl': 'sha256:old'}
        self.dataset.joinpath('dataset.json').write_text(json.dumps(payload), encoding='utf-8')

        report = diagnose.build_diagnosis(self.dataset, repo_root=ROOT)

        self.assertTrue(report['ok'])
        self.assertEqual(report['status'], 'warning')
        self.assertTrue(any(warning['check'] == 'export.latest_snapshot' for warning in report['warnings']))

    def test_missing_dataset_fails_cleanly(self):
        with self.assertRaisesRegex(FileNotFoundError, 'Dataset not found'):
            diagnose.build_diagnosis(self.knowledge / 'missing', repo_root=ROOT)


if __name__ == '__main__':
    unittest.main()
