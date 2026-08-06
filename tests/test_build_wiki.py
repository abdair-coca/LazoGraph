#!/usr/bin/env python3
"""Tests for deterministic participant-aware wiki generation."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import build_wiki
import lint_wiki


class TestBuildWiki(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dataset = Path(self.tmp.name) / 'sam'
        (self.dataset / 'sources').mkdir(parents=True)
        (self.dataset / 'wiki').mkdir()
        participants = {
            'participants': [
                {
                    'name': 'Sam Example',
                    'identity_type': 'persona',
                    'aliases': ['Sam'],
                },
                {'name': 'Alex', 'identity_type': 'contact'},
            ]
        }
        (self.dataset / 'participants.json').write_text(
            json.dumps(participants), encoding='utf-8'
        )
        messages = [
            self._message('assistant', 'Sam Example', 'Tengo clases y examen en la universidad.', '2026-01-01T10:00:00'),
            self._message('user', 'Alex', '¿Cómo estás?', '2026-01-01T10:01:00'),
            self._message('assistant', 'Sam Example', 'Trabajo en un proyecto y mañana voy a terminar el sistema.', '2026-01-02T10:00:00'),
            self._message('assistant', 'Sam Example', 'Amor de mi vida, te quiero y cuidaré siempre.', '2026-01-03T10:00:00'),
            self._message('assistant', 'Sam Example', 'Mi mamá y mi hermana van conmigo a la iglesia.', '2026-01-04T10:00:00'),
            self._message('assistant', 'Sam Example', 'Creo que debes descansar porque me preocupa tu bienestar.', '2026-01-05T10:00:00'),
            self._message('assistant', 'Sam Example', 'Fui al gym y enseñé inglés a los niños.', '2026-01-06T10:00:00'),
        ]
        source = self.dataset / 'sources' / 'chat.jsonl'
        source.write_text(
            ''.join(json.dumps(message, ensure_ascii=False) + '\n' for message in messages),
            encoding='utf-8',
        )

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def _message(role, sender, content, timestamp):
        return {
            'role': role,
            'content': content,
            'timestamp': timestamp,
            'source_file': 'chat.txt',
            'source_type': 'whatsapp',
            'metadata': {'sender': sender},
        }

    def test_dry_run_does_not_write_pages(self):
        report = build_wiki.build_wiki(self.dataset, dry_run=True)

        self.assertEqual(report['persona'], 'Sam Example')
        self.assertEqual(report['messages'], 6)
        self.assertFalse((self.dataset / 'wiki' / 'identity.md').exists())

    def test_build_writes_six_healthy_pages_with_traceable_evidence(self):
        report = build_wiki.build_wiki(self.dataset)

        self.assertEqual(report['pages'], 6)
        for page_name in build_wiki.CONTENT_PAGES:
            text = (self.dataset / 'wiki' / f'{page_name}.md').read_text(encoding='utf-8')
            self.assertIn('## Content', text)
            self.assertRegex(text, r'\[L[1-4](?::[\w-]+)?\]')
        identity = (self.dataset / 'wiki' / 'identity.md').read_text(encoding='utf-8')
        self.assertIn('Sam Example', identity)
        self.assertNotIn('¿Cómo estás?', identity)

        report = lint_wiki.lint_wiki(
            self.dataset / 'wiki',
            self.dataset,
        )
        self.assertEqual(report['issues'], [])
        warning_types = {warning['type'] for warning in report['warnings']}
        self.assertNotIn('empty_page', warning_types)
        self.assertNotIn('low_evidence', warning_types)


if __name__ == '__main__':
    unittest.main()
