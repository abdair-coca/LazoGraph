#!/usr/bin/env python3
"""Slice 1 tests for safe packaged chat import."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from lazograph.cli import build_parser, main
from lazograph.features.import_chat.service import (
    ImportValidationError,
    build_preview,
    resolve_persona,
)


FIXTURE = ROOT / "tests" / "fixtures" / "sample-whatsapp-localized.txt"


class TestImportPreview(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "knowledge"

    def tearDown(self):
        self.tmp.cleanup()

    def test_localized_fixture_has_exact_participant_counts(self):
        preview = build_preview(
            FIXTURE,
            slug="sample",
            persona="Samantha",
            root=self.root,
        )

        self.assertEqual(preview.adapter, "chat_export")
        self.assertEqual(preview.parsed_messages, 4)
        self.assertEqual(preview.rejected_notices, 1)
        self.assertEqual(preview.persona, "Samantha")
        self.assertEqual(
            [(item.name, item.identity, item.messages) for item in preview.participants],
            [("Alex", "contact", 2), ("Samantha", "persona", 2)],
        )
        self.assertEqual(preview.duplicates, 0)
        self.assertEqual(preview.new_messages, 4)

    def test_ambiguous_persona_is_rejected(self):
        with self.assertRaisesRegex(ImportValidationError, "ambiguous"):
            resolve_persona(["Sam", "Samantha", "Alex"], "Sa")

    def test_exact_persona_wins_over_partial_candidates(self):
        self.assertEqual(resolve_persona(["Sam", "Samantha"], "Sam"), "Sam")

    def test_missing_persona_lists_candidates(self):
        with self.assertRaisesRegex(ImportValidationError, "was not found"):
            resolve_persona(["Samantha", "Alex"], "Jordan")

    def test_invalid_slug_is_rejected(self):
        with self.assertRaisesRegex(ImportValidationError, "Slug"):
            build_preview(
                FIXTURE,
                slug="../sample",
                persona="Samantha",
                root=self.root,
            )

    def test_dry_run_never_creates_dataset(self):
        with patch.dict(os.environ, {"OPENPERSONA_KNOWLEDGE": str(self.root)}):
            result = main([
                "import",
                str(FIXTURE),
                "--slug",
                "sample",
                "--persona",
                "Samantha",
                "--dry-run",
            ])

        self.assertEqual(result, 0)
        self.assertFalse((self.root / "sample").exists())

    def test_cancelled_confirmation_never_creates_dataset(self):
        with (
            patch.dict(os.environ, {"OPENPERSONA_KNOWLEDGE": str(self.root)}),
            patch("builtins.input", return_value="n"),
        ):
            result = main([
                "import",
                str(FIXTURE),
                "--slug",
                "sample",
                "--persona",
                "Samantha",
            ])

        self.assertEqual(result, 1)
        self.assertFalse((self.root / "sample").exists())

    def test_same_source_reimport_is_identified(self):
        dataset = self.root / "sample"
        sources = dataset / "sources"
        sources.mkdir(parents=True)
        initial = build_preview(
            FIXTURE,
            slug="sample",
            persona="Samantha",
            root=self.root / "unused",
        )
        from adapters.chat_export import parse

        messages = parse(str(FIXTURE), persona_name="Samantha", persona_exact=True)
        sources.joinpath("chat.jsonl").write_text(
            "".join(json.dumps(message) + "\n" for message in messages),
            encoding="utf-8",
        )
        sources.joinpath(".source-index.json").write_text(
            json.dumps({"files": [{"source": str(FIXTURE.resolve())}]}),
            encoding="utf-8",
        )

        preview = build_preview(
            FIXTURE,
            slug="sample",
            persona="Samantha",
            root=self.root,
        )

        self.assertEqual(initial.new_messages, 4)
        self.assertEqual(preview.new_messages, 0)
        self.assertEqual(preview.duplicates, 4)
        self.assertTrue(preview.same_source_reimport)

    def test_equivalent_backup_stops_before_writes(self):
        candidate = Path(self.tmp.name) / "candidate.txt"
        lines = []
        for index in range(20):
            sender = "Samantha" if index % 2 == 0 else "Alex"
            lines.append(f"13/8/25, 9:{index:02d} p. m. - {sender}: Message {index}\n")
        candidate.write_text("".join(lines), encoding="utf-8")

        dataset = self.root / "sample"
        sources = dataset / "sources"
        sources.mkdir(parents=True)
        from adapters.chat_export import parse

        messages = parse(str(candidate), persona_name="Samantha", persona_exact=True)
        sources.joinpath("backup.jsonl").write_text(
            "".join(json.dumps(message) + "\n" for message in messages),
            encoding="utf-8",
        )
        before = {
            path.relative_to(dataset): path.read_bytes()
            for path in dataset.rglob("*")
            if path.is_file()
        }

        with patch.dict(os.environ, {"OPENPERSONA_KNOWLEDGE": str(self.root)}):
            result = main([
                "import",
                str(candidate),
                "--slug",
                "sample",
                "--persona",
                "Samantha",
                "--yes",
            ])

        after = {
            path.relative_to(dataset): path.read_bytes()
            for path in dataset.rglob("*")
            if path.is_file()
        }
        self.assertEqual(result, 2)
        self.assertEqual(after, before)


class TestImportCLIArguments(unittest.TestCase):
    def test_parser_exposes_slice_one_interface(self):
        args = build_parser().parse_args([
            "import",
            "chat.txt",
            "--slug",
            "sample",
            "--persona",
            "Samantha",
        ])
        self.assertEqual(args.command, "import")
        self.assertEqual(args.source, "chat.txt")
        self.assertEqual(args.slug, "sample")
        self.assertEqual(args.persona, "Samantha")

    def test_equivalent_source_options_are_mutually_exclusive(self):
        with self.assertRaises(SystemExit):
            build_parser().parse_args([
                "import",
                "chat.txt",
                "--slug",
                "sample",
                "--persona",
                "Samantha",
                "--allow-equivalent-source",
                "--reconcile-equivalent-source",
            ])


class TestLegacyScriptCompatibility(unittest.TestCase):
    def test_stats_survives_legacy_windows_code_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            dataset = root / "sample"
            (dataset / "sources").mkdir(parents=True)
            (dataset / "wiki").mkdir()
            dataset.joinpath("dataset.json").write_text(
                json.dumps({
                    "slug": "sample",
                    "name": "Samantha",
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "stats": {},
                }),
                encoding="utf-8",
            )
            env = os.environ.copy()
            env["OPENPERSONA_KNOWLEDGE"] = str(root)
            env["PYTHONIOENCODING"] = "cp1252"
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "init_knowledge.py"),
                    "--slug",
                    "sample",
                    "--stats",
                ],
                env=env,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Dataset: Samantha", result.stdout)


if __name__ == "__main__":
    unittest.main()
