#!/usr/bin/env python3
"""Regression tests for localized WhatsApp exports."""

import tempfile
import unittest
from pathlib import Path

from adapters import detect_adapter
from adapters.chat_export import parse


class TestLocalizedWhatsApp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'chat.txt'

    def tearDown(self):
        self.tmp.cleanup()

    def write_chat(self, text: str):
        self.path.write_text(text, encoding='utf-8')

    def test_spanish_android_export_is_auto_detected(self):
        self.write_chat(
            '13/8/25, 9:38\u202fp.\u202fm. - Los mensajes están cifrados.\n'
            '13/8/25, 9:39\u202fp.\u202fm. - Abdair: Hola\n'
        )

        self.assertEqual(detect_adapter(str(self.path)), 'chat_export')

    def test_spanish_timestamp_and_multiline_content(self):
        self.write_chat(
            '13/8/25, 9:38\u202fp.\u202fm. - Los mensajes están cifrados.\n'
            '13/8/25, 9:39\u202fp.\u202fm. - Abdair: Primera línea\n'
            'segunda línea\n'
            '13/8/25, 9:40\u00a0p.\u00a0m. - Alizon: Respuesta\n'
        )

        messages = parse(str(self.path), persona_name='Abdair')

        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]['role'], 'assistant')
        self.assertEqual(messages[0]['content'], 'Primera línea\nsegunda línea')
        self.assertEqual(messages[0]['timestamp'], '2025-08-13T21:39:00')
        self.assertEqual(messages[1]['role'], 'user')
        self.assertEqual(messages[1]['metadata']['sender'], 'Alizon')

    def test_ios_bracket_export_with_seconds(self):
        self.write_chat(
            '[13/8/25, 9:38:05 a. m.] Abdair: Mensaje desde iOS\n'
        )

        messages = parse(str(self.path), persona_name='Abdair')

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]['timestamp'], '2025-08-13T09:38:05')

    def test_english_month_first_export_still_works(self):
        self.write_chat('8/13/25, 9:38 PM - Sam: Hello\n')

        messages = parse(str(self.path), persona_name='Sam')

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]['timestamp'], '2025-08-13T21:38:00')

    def test_system_notice_with_colon_is_not_a_participant(self):
        self.write_chat(
            '13/8/25, 9:38 p. m. - Se actualizó la duración de los mensajes: 7 días\n'
            '13/8/25, 9:39 p. m. - Abdair: Mensaje real\n'
        )

        messages = parse(str(self.path), persona_name='Abdair')

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]['metadata']['sender'], 'Abdair')


if __name__ == '__main__':
    unittest.main()
