#!/usr/bin/env python3
"""Tests for authentic source dialogue export."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import export_training


class TestSourceDialogueExport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.source = Path(self.tmp.name) / 'chat.jsonl'

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, messages):
        self.source.write_text(
            ''.join(json.dumps(message) + '\n' for message in messages),
            encoding='utf-8',
        )

    def test_preserves_real_roles_and_groups_consecutive_messages(self):
        self._write([
            {'role': 'assistant', 'content': 'Unmatched opening.'},
            {'role': 'user', 'content': 'Question one.'},
            {'role': 'user', 'content': 'Question two.'},
            {'role': 'assistant', 'content': 'Answer one.'},
            {'role': 'assistant', 'content': 'Answer two.'},
        ])

        turns = export_training._load_source_dialogue(self.source)

        self.assertEqual(turns, [
            {'role': 'user', 'content': 'Question one.\nQuestion two.'},
            {'role': 'assistant', 'content': 'Answer one.\nAnswer two.'},
        ])
        self.assertNotIn('Go on.', {turn['content'] for turn in turns})

    def test_does_not_export_assistant_only_source_with_invented_prompt(self):
        self._write([{'role': 'assistant', 'content': 'No user context.'}])

        turns = export_training._load_source_dialogue(self.source)

        self.assertEqual(turns, [])

    def test_discards_unanswered_trailing_user_turn(self):
        self._write([
            {'role': 'user', 'content': 'Answered question.'},
            {'role': 'assistant', 'content': 'Answer.'},
            {'role': 'user', 'content': 'Unanswered question.'},
        ])

        turns = export_training._load_source_dialogue(self.source)

        self.assertEqual(turns[-1], {'role': 'assistant', 'content': 'Answer.'})
        self.assertEqual(len(turns), 2)


if __name__ == '__main__':
    unittest.main()
