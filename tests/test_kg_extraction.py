#!/usr/bin/env python3
"""Regression tests for conservative KG NER, coreference, and confidence."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import kg_extraction


class TestKGExtraction(unittest.TestCase):
    def test_context_and_multiword_ner_accept_people(self):
        facts = kg_extraction.extract_message_facts(
            'Ayer hablé con Carla. Luego, Diego Mendoza me llamó.',
            sender='Sam',
            known_names=set(),
        )

        names = {item['name'] for item in facts['mentions']}
        self.assertEqual(names, {'Carla', 'Diego Mendoza'})

    def test_calendar_and_greeting_words_are_rejected(self):
        facts = kg_extraction.extract_message_facts(
            'Mañana Trabajo Importante. Buenas noches.',
            sender='Sam',
            known_names=set(),
        )

        self.assertEqual(facts['mentions'], [])

    def test_bounded_coreference_uses_recent_unambiguous_person(self):
        messages = [
            {'role': 'assistant', 'content': 'Hablé con Carla.', 'metadata': {'sender': 'Sam'}},
            {'role': 'assistant', 'content': 'Ella es mi jefa.', 'metadata': {'sender': 'Sam'}},
        ]

        facts = kg_extraction.extract_content_facts(messages, {'Sam'})

        relationship = next(item for item in facts['relationships'] if item['type'] == 'reports_to')
        self.assertEqual(relationship['from'], 'Carla')
        self.assertEqual(relationship['to'], 'Sam')
        self.assertEqual(relationship['confidence'], 0.84)

    def test_coreference_expires_after_two_messages(self):
        messages = [
            {'role': 'assistant', 'content': 'Hablé con Carla.', 'metadata': {'sender': 'Sam'}},
            {'role': 'assistant', 'content': 'Uno.', 'metadata': {'sender': 'Sam'}},
            {'role': 'assistant', 'content': 'Dos.', 'metadata': {'sender': 'Sam'}},
            {'role': 'assistant', 'content': 'Tres.', 'metadata': {'sender': 'Sam'}},
            {'role': 'assistant', 'content': 'Ella es mi jefa.', 'metadata': {'sender': 'Sam'}},
        ]

        facts = kg_extraction.extract_content_facts(messages, {'Sam'})

        self.assertFalse(any(item['type'] == 'reports_to' for item in facts['relationships']))

    def test_labeled_evaluation_reports_false_positives(self):
        report = kg_extraction.evaluate_cases([
            {'text': 'Hablé con Carla.', 'expected_entities': ['Carla']},
            {'text': 'Mañana trabajo.', 'expected_entities': []},
        ])

        self.assertEqual(report['precision'], 1.0)
        self.assertEqual(report['recall'], 1.0)
        self.assertEqual(report['f1'], 1.0)


if __name__ == '__main__':
    unittest.main()
