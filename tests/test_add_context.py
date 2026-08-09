#!/usr/bin/env python3
"""Slice 3 manual-context preflight tests."""

import json
import os
import sys
import tempfile
import unittest
import gc
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from lazograph.cli import build_parser, main
from lazograph.features.add_context import ContextValidationError, build_context_preview
from lazograph.features.add_context import apply_context
from lazograph.features.ask_person.service import answer_about_person
from lazograph.domain.answer import Evidence
from lazograph.infrastructure.llm import HostedProvider, LocalExtractiveProvider
from scripts.dataset_invariants import validate_dataset


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
            "metadata": {
                "sender": record.subject,
                "subject": record.subject,
                "record_kind": record.kind,
                "authority": record.authority,
            },
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

    def test_apply_persists_provenance_and_is_idempotent(self):
        source = self.source("ASSERT: Alex cumple años en marzo.")
        preview = build_context_preview(source, self.dataset, now=self.now)
        healthy = {"ok": True, "errors": [], "warnings": []}
        with (
            patch("lazograph.features.add_context.service._vector_ids", return_value=set()),
            patch("scripts.ingest._store_in_mempalace", return_value=1) as store,
            patch("scripts.dataset_invariants.validate_dataset", return_value=healthy),
        ):
            result = apply_context(preview)

        self.assertEqual(result.stored_records, 1)
        self.assertEqual(result.vector_count, 1)
        backup = self.dataset / "sources" / result.source_file
        persisted = json.loads(backup.read_text(encoding="utf-8").strip())
        self.assertEqual(persisted["source_type"], "user_context")
        self.assertEqual(persisted["metadata"]["authority"], "user_assertion")
        self.assertEqual(persisted["metadata"]["confidence"], 1.0)
        index = json.loads(
            self.dataset.joinpath("sources", ".source-index.json").read_text(encoding="utf-8")
        )
        self.assertEqual(index["files"][0]["source_sha256"], preview.source_sha256)
        self.assertEqual(index["files"][0]["authored_by"], "dataset_owner")
        store.assert_called_once()

        second = build_context_preview(source, self.dataset, now=self.now)
        with (
            patch("scripts.ingest._store_in_mempalace") as second_store,
            patch("scripts.dataset_invariants.validate_dataset", return_value=healthy),
        ):
            repeated = apply_context(second)
        self.assertEqual(repeated.stored_records, 0)
        self.assertEqual(repeated.duplicates, 1)
        second_store.assert_not_called()

    def test_apply_rejects_source_changed_after_preview(self):
        source = self.source("ASSERT: Alex cumple años en marzo.")
        preview = build_context_preview(source, self.dataset, now=self.now)
        source.write_text("ASSERT: Alex cumple años en abril.", encoding="utf-8")
        with self.assertRaisesRegex(ContextValidationError, "changed after preflight"):
            apply_context(preview)

    def test_failed_apply_restores_files_and_new_vectors(self):
        source = self.source("ASSERT: Alex cumple años en marzo.")
        preview = build_context_preview(source, self.dataset, now=self.now)
        before = {
            path.relative_to(self.dataset): path.read_bytes()
            for path in self.dataset.rglob("*") if path.is_file()
        }
        unhealthy = {"ok": False, "errors": [{"check": "vectors.count"}], "warnings": []}
        with (
            patch(
                "lazograph.features.add_context.service._vector_ids",
                side_effect=[set(), {"sample-new"}],
            ),
            patch("lazograph.features.add_context.service._delete_vectors") as delete,
            patch("scripts.ingest._store_in_mempalace", return_value=1),
            patch("scripts.dataset_invariants.validate_dataset", return_value=unhealthy),
        ):
            with self.assertRaisesRegex(RuntimeError, "rolled back"):
                apply_context(preview)
        after = {
            path.relative_to(self.dataset): path.read_bytes()
            for path in self.dataset.rglob("*") if path.is_file()
        }
        self.assertEqual(after, before)
        delete.assert_called_once_with(self.dataset, {"sample-new"})


class TestContextCLI(unittest.TestCase):
    def test_context_requires_exactly_one_action(self):
        parser = build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["context", "context.txt", "--slug", "sample"])
        with self.assertRaises(SystemExit):
            parser.parse_args([
                "context", "context.txt", "--slug", "sample", "--dry-run", "--apply"
            ])


class TestContextProviderBoundary(unittest.TestCase):
    def test_hosted_provider_gets_selected_provenance_not_source_path_or_hash(self):
        captured = {}
        evidence = Evidence(
            message_id="context.jsonl:1",
            sender="Alex",
            source_file="context.jsonl",
            timestamp=None,
            excerpt="Alex cumple años en marzo.",
            score=0.9,
            source_type="user_context",
            record_kind="assertion",
            authority="user_assertion",
            authored_by="dataset_owner",
            confidence=1.0,
            imported_at="2026-08-08T12:00:00+00:00",
        )

        def transport(_url, _headers, payload):
            captured["payload"] = payload
            return {"choices": [{"message": {"content": json.dumps({
                "text": "Cumple años en marzo [context.jsonl:1]",
                "citation_ids": ["context.jsonl:1"],
                "confidence": 0.9,
                "abstained": False,
            })}}]}

        provider = HostedProvider(
            url="https://provider.invalid/chat",
            model="test-model",
            api_key="test-key",
            transport=transport,
        )
        provider.generate("¿Cuándo cumple años?", "Alex", [evidence], {}, language="es")
        serialized = json.dumps(captured["payload"], ensure_ascii=False)
        self.assertIn("user_assertion", serialized)
        self.assertIn("dataset_owner", serialized)
        self.assertNotIn("sha256:", serialized)
        self.assertNotIn("C:\\\\", serialized)


class TestContextEndToEnd(unittest.TestCase):
    def test_import_context_ask_and_repeat_apply(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "knowledge"
            context_source = Path(tmp) / "context.txt"
            context_source.write_text(
                "ASSERT: Alex cumple años el 14 de marzo.",
                encoding="utf-8",
            )
            output = StringIO()
            with (
                patch.dict(os.environ, {"OPENPERSONA_KNOWLEDGE": str(root)}),
                redirect_stdout(output),
                redirect_stderr(output),
            ):
                imported = main([
                    "import",
                    str(ROOT / "tests" / "fixtures" / "sample-whatsapp-localized.txt"),
                    "--slug",
                    "sample",
                    "--persona",
                    "Samantha",
                    "--yes",
                ])
                applied = main([
                    "context",
                    str(context_source),
                    "--slug",
                    "sample",
                    "--apply",
                ])

            self.assertEqual(imported, 0, output.getvalue())
            self.assertEqual(applied, 0, output.getvalue())
            dataset = root / "sample"
            invariants = validate_dataset(dataset)
            self.assertTrue(invariants["ok"], invariants)

            answer = answer_about_person(
                dataset,
                "¿Cuándo cumple años Alex?",
                "Alex",
                LocalExtractiveProvider(),
                limit=3,
            )
            self.assertFalse(answer.abstained)
            context_evidence = [
                item for item in answer.citations if item.source_type == "user_context"
            ]
            self.assertTrue(context_evidence)
            self.assertEqual(context_evidence[0].record_kind, "assertion")
            self.assertEqual(context_evidence[0].authority, "user_assertion")
            self.assertEqual(context_evidence[0].confidence, 1.0)
            self.assertIn("evidencia guardada", answer.text)

            before = {
                path.relative_to(dataset): path.read_bytes()
                for path in dataset.rglob("*") if path.is_file()
            }
            repeat_output = StringIO()
            with (
                patch.dict(os.environ, {"OPENPERSONA_KNOWLEDGE": str(root)}),
                redirect_stdout(repeat_output),
                redirect_stderr(repeat_output),
            ):
                repeated = main([
                    "context",
                    str(context_source),
                    "--slug",
                    "sample",
                    "--apply",
                ])
            after = {
                path.relative_to(dataset): path.read_bytes()
                for path in dataset.rglob("*") if path.is_file()
            }
            self.assertEqual(repeated, 0, repeat_output.getvalue())
            self.assertIn("Already stored", repeat_output.getvalue())
            self.assertEqual(after, before)
            from chromadb.api.client import SharedSystemClient

            SharedSystemClient.clear_system_cache()
            gc.collect()


if __name__ == "__main__":
    unittest.main()
