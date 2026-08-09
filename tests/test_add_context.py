#!/usr/bin/env python3
"""Slice 3 manual-context preflight tests."""

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from lazograph.cli import build_parser, main
from lazograph.features.add_context import ContextValidationError, build_context_preview


class ContextFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "knowledge"
        self.dataset = self.root / "sample"
        (self.dataset / "sources").mkdir(parents=True)
        self.dataset.joinpath("dataset.json").write_text(
            json.dumps({"slug": "sample", "name": "Samantha", "stats": {}}),
            encoding="utf-8",
        )
        self.dataset.joinpath("participants.json").write_text(
            json.dumps({
                "schema_version": 2,
                "participants": [
                    {"name": "Samantha", "aliases": ["Sam"], "identity_type": "persona"},
                    {"name": "Alex", "aliases": ["Alexis"], "identity_type": "contact"},
                ],
            }),
            encoding="utf-8",
        )
        self.now = datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)

    def tearDown(self):
        self.tmp.cleanup()

    def source(self, content: str) -> Path:
        path = Path(self.tmp.name) / "context.txt"
        path.write_text(content, encoding="utf-8")
        return path


class TestContextPreview(ContextFixture):
    def test_classifies_assertion_freeform_and_inference(self):
        preview = build_context_preview(
            self.source(
                "ASSERT: Alex cumple años el 14 de marzo.\n\n"
                "CONTEXTO: Alex habló de flores.\n\n"
                "INFERENCIA: Alex quizá prefiera tulipanes."
            ),
            self.dataset,
            now=self.now,
        )

        self.assertEqual(
            [(item.kind, item.confidence, item.authority) for item in preview.records],
            [
                ("assertion", 1.0, "user_assertion"),
                ("freeform", 0.75, "user_context"),
                ("inference", 0.5, "user_inference"),
            ],
        )
        self.assertTrue(all(item.subject == "Alex" for item in preview.records))

    def test_plain_multiline_paragraph_is_one_freeform_record(self):
        preview = build_context_preview(
            self.source("Alex habló de su proyecto.\nDijo que está avanzando bien."),
            self.dataset,
            now=self.now,
        )
        self.assertEqual(len(preview.records), 1)
        self.assertEqual(preview.records[0].kind, "freeform")
        self.assertEqual(
            preview.records[0].content,
            "Alex habló de su proyecto. Dijo que está avanzando bien.",
        )

    def test_about_resolves_alias_and_supports_implicit_subject(self):
        preview = build_context_preview(
            self.source("ASSERT: Cumple años en marzo."),
            self.dataset,
            about="Alexis",
            now=self.now,
        )
        self.assertEqual(preview.records[0].subject, "Alex")

    def test_missing_or_ambiguous_subject_is_rejected(self):
        with self.assertRaisesRegex(ContextValidationError, "does not identify"):
            build_context_preview(
                self.source("Una nota sin nombre."), self.dataset, now=self.now
            )
        with self.assertRaisesRegex(ContextValidationError, "multiple participants"):
            build_context_preview(
                self.source("Alex y Samantha harán algo."), self.dataset, now=self.now
            )

    def test_source_hash_and_pii_are_reported(self):
        preview = build_context_preview(
            self.source("Alex puede usar alex@example.com."),
            self.dataset,
            now=self.now,
        )
        self.assertRegex(preview.source_sha256, r"^sha256:[0-9a-f]{64}$")
        self.assertIn("email", preview.pii_flags)

    def test_existing_context_is_detected_without_writes(self):
        source = self.source("ASSERT: Alex cumple años en marzo.")
        first = build_context_preview(source, self.dataset, now=self.now)
        record = first.records[0]
        message = {
            "role": "user",
            "content": record.content,
            "timestamp": self.now.isoformat(),
            "source_file": source.name,
            "source_type": "user_context",
            "metadata": {"sender": record.subject},
        }
        self.dataset.joinpath("sources", "context.jsonl").write_text(
            json.dumps(message) + "\n", encoding="utf-8"
        )
        preview = build_context_preview(source, self.dataset, now=self.now)
        self.assertEqual(preview.duplicates, 1)
        self.assertEqual(preview.new_records, 0)

    def test_dry_run_never_mutates_dataset(self):
        source = self.source("ASSERT: Alex cumple años en marzo.")
        before = {path.relative_to(self.dataset): path.read_bytes() for path in self.dataset.rglob("*") if path.is_file()}
        with patch.dict(os.environ, {"OPENPERSONA_KNOWLEDGE": str(self.root)}):
            result = main(["context", str(source), "--slug", "sample", "--dry-run"])
        after = {path.relative_to(self.dataset): path.read_bytes() for path in self.dataset.rglob("*") if path.is_file()}
        self.assertEqual(result, 0)
        self.assertEqual(after, before)


class TestContextCLI(unittest.TestCase):
    def test_context_requires_exactly_one_action(self):
        parser = build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["context", "context.txt", "--slug", "sample"])
        with self.assertRaises(SystemExit):
            parser.parse_args([
                "context", "context.txt", "--slug", "sample", "--dry-run", "--apply"
            ])


if __name__ == "__main__":
    unittest.main()
