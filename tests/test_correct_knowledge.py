#!/usr/bin/env python3
"""Slice 4 correction parsing and dry-run tests."""

import json
import os
import sqlite3
import sys
import tempfile
import unittest
import gc
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from lazograph.cli import build_parser, main
from lazograph.features.correct_knowledge import (
    CorrectionLedgerError,
    CorrectionValidationError,
    apply_correction,
    build_correction_preview,
    correction_records,
    undo_correction,
)
from lazograph.features.correct_knowledge.ledger import append_correction
from lazograph.features.ask_person.service import answer_about_person
from lazograph.infrastructure.llm import LocalExtractiveProvider
from lazograph.domain.answer import ProviderOutput
from scripts import query_kg
from scripts import rebuild_all


class CorrectionFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "knowledge"
        self.dataset = self.root / "sample"
        palace = self.dataset / ".mempalace" / "palace"
        palace.mkdir(parents=True)
        self.dataset.joinpath("dataset.json").write_text(
            json.dumps({"slug": "sample", "name": "Samantha"}), encoding="utf-8"
        )
        self.dataset.joinpath("participants.json").write_text(
            json.dumps({"participants": [
                {"name": "Carlos", "aliases": ["Carlitos"]},
                {"name": "Juan", "aliases": ["Juanito"]},
            ]}),
            encoding="utf-8",
        )
        connection = sqlite3.connect(palace / "knowledge_graph.sqlite3")
        connection.execute("CREATE TABLE entities (id TEXT PRIMARY KEY, name TEXT)")
        connection.executemany(
            "INSERT INTO entities VALUES (?, ?)",
            [("1", "Carlos"), ("2", "Juan")],
        )
        connection.execute(
            "CREATE TABLE triples (subject TEXT, predicate TEXT, object TEXT, "
            "confidence REAL, source_file TEXT, valid_from TEXT)"
        )
        connection.execute(
            "INSERT INTO triples VALUES (?, ?, ?, ?, ?, ?)",
            ("1", "sibling_of", "2", 0.84, "chat.jsonl", "2026-01-01T00:00:00"),
        )
        connection.commit()
        connection.close()

    def tearDown(self):
        self.tmp.cleanup()


class TestCorrectionPreview(CorrectionFixture):
    def test_english_correction_resolves_exact_claim(self):
        preview = build_correction_preview(
            "Carlos is Juan's cousin, not his brother",
            self.dataset,
        )
        self.assertEqual(preview.retract.predicate, "sibling_of")
        self.assertEqual(preview.assert_claim.predicate, "cousin_of")
        self.assertEqual(preview.assert_claim.subject, "Carlos")
        self.assertEqual(preview.assert_claim.object, "Juan")
        self.assertEqual(len(preview.matched_claims), 1)
        self.assertRegex(preview.fingerprint, r"^sha256:[0-9a-f]{64}$")

    def test_spanish_correction_and_aliases_resolve_canonically(self):
        preview = build_correction_preview(
            "Carlitos no es hermano de Juanito, es su primo",
            self.dataset,
        )
        self.assertEqual(preview.retract.subject, "Carlos")
        self.assertEqual(preview.retract.object, "Juan")
        self.assertEqual(preview.retract.predicate, "sibling_of")
        self.assertEqual(preview.assert_claim.predicate, "cousin_of")

    def test_unknown_relation_and_missing_claim_are_rejected(self):
        with self.assertRaisesRegex(CorrectionValidationError, "Unsupported relationship"):
            build_correction_preview(
                "Carlos is Juan's wizard, not his brother", self.dataset
            )
        with self.assertRaisesRegex(CorrectionValidationError, "No effective"):
            build_correction_preview(
                "Carlos is Juan's cousin, not his friend", self.dataset
            )

    def test_ambiguous_partial_entity_is_rejected(self):
        payload = json.loads(
            self.dataset.joinpath("participants.json").read_text(encoding="utf-8")
        )
        payload["participants"].append({"name": "Carlota", "aliases": []})
        self.dataset.joinpath("participants.json").write_text(json.dumps(payload), encoding="utf-8")
        connection = sqlite3.connect(
            self.dataset / ".mempalace" / "palace" / "knowledge_graph.sqlite3"
        )
        connection.execute("INSERT INTO entities VALUES (?, ?)", ("3", "Carlota"))
        connection.commit()
        connection.close()
        with self.assertRaisesRegex(CorrectionValidationError, "ambiguous"):
            build_correction_preview(
                "Carl is Juan's cousin, not his brother", self.dataset
            )

    def test_dry_run_does_not_mutate_dataset(self):
        before = {
            path.relative_to(self.dataset): path.read_bytes()
            for path in self.dataset.rglob("*") if path.is_file()
        }
        with patch.dict(os.environ, {"OPENPERSONA_KNOWLEDGE": str(self.root)}):
            result = main([
                "correct",
                "Carlos no es hermano de Juan, es su primo",
                "--slug",
                "sample",
                "--dry-run",
            ])
        after = {
            path.relative_to(self.dataset): path.read_bytes()
            for path in self.dataset.rglob("*") if path.is_file()
        }
        self.assertEqual(result, 0)
        self.assertEqual(after, before)

    def test_pii_is_reported_before_apply(self):
        connection = sqlite3.connect(
            self.dataset / ".mempalace" / "palace" / "knowledge_graph.sqlite3"
        )
        connection.execute("UPDATE entities SET name = ? WHERE id = ?", ("carlos@example.com", "1"))
        connection.commit()
        connection.close()
        payload = json.loads(self.dataset.joinpath("participants.json").read_text(encoding="utf-8"))
        payload["participants"][0] = {"name": "carlos@example.com", "aliases": []}
        self.dataset.joinpath("participants.json").write_text(json.dumps(payload), encoding="utf-8")
        preview = build_correction_preview(
            "carlos@example.com is Juan's cousin, not his brother",
            self.dataset,
        )
        self.assertIn("email", preview.pii_flags)


class TestCorrectionLedger(CorrectionFixture):
    def apply(self):
        preview = build_correction_preview(
            "Carlos no es hermano de Juan, es su primo",
            self.dataset,
        )
        return apply_correction(preview)

    def test_apply_preserves_generated_db_and_projects_effective_graph(self):
        db_path = self.dataset / ".mempalace" / "palace" / "knowledge_graph.sqlite3"
        before = db_path.read_bytes()
        result = self.apply()
        after = db_path.read_bytes()

        self.assertTrue(result["appended"])
        self.assertRegex(result["record"]["claim_id"], r"^claim-[0-9a-f]{16}$")
        self.assertEqual(before, after)
        events = self.dataset.joinpath("corrections", "ledger.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        self.assertEqual(len(events), 1)
        entities, relationships, stats = query_kg._load_kg(self.dataset)
        self.assertEqual(entities, {"Carlos", "Juan"})
        self.assertFalse(any(item["type"] == "sibling_of" for item in relationships))
        effective = next(item for item in relationships if item["type"] == "cousin_of")
        self.assertEqual(effective["confidence"], 1.0)
        self.assertEqual(effective["authority"], "user")
        self.assertEqual(effective["provenance"], "user_correction")
        self.assertEqual(stats["active_corrections"], 1)
        self.assertEqual(stats["retracted_relationships"], 1)

    def test_reapply_is_idempotent(self):
        first = self.apply()
        repeated_preview = build_correction_preview(
            "Carlos no es hermano de Juan, es su primo",
            self.dataset,
        )
        self.assertTrue(repeated_preview.already_applied)
        repeated = apply_correction(repeated_preview)
        self.assertFalse(repeated["appended"])
        self.assertEqual(repeated["record"]["claim_id"], first["record"]["claim_id"])
        lines = self.dataset.joinpath("corrections", "ledger.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        self.assertEqual(len(lines), 1)

    def test_undo_appends_history_and_restores_generated_claim(self):
        applied = self.apply()
        claim_id = applied["record"]["claim_id"]
        result = undo_correction(self.dataset, claim_id)

        self.assertTrue(result["appended"])
        self.assertRegex(result["event"]["event_id"], r"^undo-[0-9a-f]{16}$")
        records = correction_records(self.dataset)
        self.assertEqual(records[0]["status"], "undone")
        lines = self.dataset.joinpath("corrections", "ledger.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        self.assertEqual(len(lines), 2)
        _entities, relationships, stats = query_kg._load_kg(self.dataset)
        self.assertTrue(any(item["type"] == "sibling_of" for item in relationships))
        self.assertFalse(any(item["type"] == "cousin_of" for item in relationships))
        self.assertEqual(stats["active_corrections"], 0)

        repeated = undo_correction(self.dataset, claim_id)
        self.assertFalse(repeated["appended"])
        self.assertEqual(
            len(self.dataset.joinpath("corrections", "ledger.jsonl").read_text(encoding="utf-8").splitlines()),
            2,
        )

    def test_assertion_or_retraction_id_can_undo_atomic_correction(self):
        applied = self.apply()
        assertion_id = applied["record"]["assert"]["claim_id"]
        result = undo_correction(self.dataset, assertion_id)
        self.assertTrue(result["appended"])
        self.assertEqual(result["record"]["status"], "undone")

    def test_corrupt_or_locked_ledger_fails_without_graph_mutation(self):
        corrections = self.dataset / "corrections"
        corrections.mkdir()
        corrections.joinpath("ledger.jsonl").write_text("not-json\n", encoding="utf-8")
        with self.assertRaisesRegex(CorrectionLedgerError, "invalid"):
            query_kg._load_kg(self.dataset)
        corrections.joinpath("ledger.jsonl").unlink()
        corrections.joinpath(".ledger.lock").mkdir()
        preview = build_correction_preview(
            "Carlos no es hermano de Juan, es su primo", self.dataset
        )
        with self.assertRaisesRegex(CorrectionLedgerError, "locked"):
            apply_correction(preview)
        self.assertFalse(corrections.joinpath("ledger.jsonl").exists())

    def test_cli_apply_list_and_undo(self):
        with patch.dict(os.environ, {"OPENPERSONA_KNOWLEDGE": str(self.root)}):
            applied = main([
                "correct",
                "Carlos no es hermano de Juan, es su primo",
                "--slug",
                "sample",
                "--apply",
            ])
            records = correction_records(self.dataset)
            listed = main(["corrections", "--slug", "sample", "list"])
            undone = main([
                "corrections",
                "--slug",
                "sample",
                "undo",
                records[0]["claim_id"],
            ])
        self.assertEqual((applied, listed, undone), (0, 0, 0))

    def test_active_correction_is_citable_and_undo_removes_it(self):
        applied = self.apply()

        def no_memories(_dataset, _query, *, participant, limit):
            del participant, limit
            return []

        answer = answer_about_person(
            self.dataset,
            "¿Carlos es primo o hermano de Juan?",
            "Carlos",
            LocalExtractiveProvider(),
            memory_search=no_memories,
        )
        self.assertFalse(answer.abstained)
        self.assertEqual(len(answer.citations), 1)
        citation = answer.citations[0]
        self.assertEqual(citation.source_type, "user_correction")
        self.assertEqual(citation.authority, "user")
        self.assertEqual(citation.message_id, f'correction:{applied["record"]["claim_id"]}')
        self.assertIn("evidencia guardada", answer.text)

        undo_correction(self.dataset, applied["record"]["claim_id"])
        after_undo = answer_about_person(
            self.dataset,
            "¿Carlos es primo o hermano de Juan?",
            "Carlos",
            LocalExtractiveProvider(),
            memory_search=no_memories,
        )
        self.assertTrue(after_undo.abstained)
        self.assertEqual(after_undo.citations, ())

    def test_generated_graph_replacement_keeps_active_correction_effective(self):
        self.apply()
        db_path = self.dataset / ".mempalace" / "palace" / "knowledge_graph.sqlite3"
        connection = sqlite3.connect(db_path)
        connection.execute("DELETE FROM triples")
        connection.execute(
            "INSERT INTO triples VALUES (?, ?, ?, ?, ?, ?)",
            ("1", "sibling_of", "2", 0.96, "rebuilt.jsonl", "2026-08-09T00:00:00"),
        )
        connection.commit()
        connection.close()

        _entities, relationships, _stats = query_kg._load_kg(self.dataset)
        self.assertFalse(any(item["type"] == "sibling_of" for item in relationships))
        corrected = next(item for item in relationships if item["type"] == "cousin_of")
        self.assertEqual(corrected["source"].split(":", 1)[0], "correction")

    def test_superseding_correction_and_undo_restore_previous_user_claim(self):
        first = self.apply()
        second_preview = build_correction_preview(
            "Carlos no es primo de Juan, es su amigo",
            self.dataset,
        )
        self.assertEqual(
            second_preview.matched_claims[0].claim_id,
            first["record"]["assert"]["claim_id"],
        )
        second = apply_correction(second_preview)
        self.assertEqual(
            second["record"]["supersedes"],
            [first["record"]["assert"]["claim_id"]],
        )
        _entities, relationships, _stats = query_kg._load_kg(self.dataset)
        self.assertTrue(any(item["type"] == "friend_of" for item in relationships))
        self.assertFalse(any(item["type"] == "cousin_of" for item in relationships))

        undo_correction(self.dataset, second["record"]["claim_id"])
        _entities, restored, _stats = query_kg._load_kg(self.dataset)
        self.assertTrue(any(item["type"] == "cousin_of" for item in restored))
        self.assertFalse(any(item["type"] == "friend_of" for item in restored))

    def test_stale_concurrent_preview_cannot_replace_same_claim_twice(self):
        first = build_correction_preview(
            "Carlos no es hermano de Juan, es su primo", self.dataset
        )
        conflicting = build_correction_preview(
            "Carlos no es hermano de Juan, es su amigo", self.dataset
        )
        append_correction(self.dataset, first)
        with self.assertRaisesRegex(CorrectionLedgerError, "already retracts"):
            append_correction(self.dataset, conflicting)
        self.assertEqual(len(correction_records(self.dataset)), 1)

    def test_base_claim_id_survives_source_and_timestamp_changes(self):
        applied = self.apply()
        original_base_id = applied["record"]["matched_claim_ids"][0]
        undo_correction(self.dataset, applied["record"]["claim_id"])
        db_path = self.dataset / ".mempalace" / "palace" / "knowledge_graph.sqlite3"
        connection = sqlite3.connect(db_path)
        connection.execute(
            "UPDATE triples SET source_file = ?, valid_from = ?",
            ("rebuilt.jsonl", "2030-01-01T00:00:00"),
        )
        connection.commit()
        connection.close()
        rebuilt_preview = build_correction_preview(
            "Carlos no es hermano de Juan, es su primo", self.dataset
        )
        self.assertEqual(rebuilt_preview.matched_claims[0].claim_id, original_base_id)

    def test_answer_provider_never_receives_unrelated_participant_correction(self):
        connection = sqlite3.connect(
            self.dataset / ".mempalace" / "palace" / "knowledge_graph.sqlite3"
        )
        connection.executemany(
            "INSERT INTO entities VALUES (?, ?)",
            [("3", "Alice"), ("4", "Bob")],
        )
        connection.execute(
            "INSERT INTO triples VALUES (?, ?, ?, ?, ?, ?)",
            ("3", "sibling_of", "4", 0.84, "other.jsonl", None),
        )
        connection.commit()
        connection.close()
        payload = json.loads(self.dataset.joinpath("participants.json").read_text(encoding="utf-8"))
        payload["participants"].extend([
            {"name": "Alice", "aliases": []},
            {"name": "Bob", "aliases": []},
        ])
        self.dataset.joinpath("participants.json").write_text(json.dumps(payload), encoding="utf-8")
        self.apply()
        apply_correction(build_correction_preview(
            "Alice is Bob's cousin, not her sister", self.dataset
        ))

        class CaptureProvider:
            name = "capture"
            hosted = True

            def __init__(self):
                self.evidence = []

            def generate(self, question, participant, evidence, context, *, language):
                del question, participant, context, language
                self.evidence = list(evidence)
                first = evidence[0]
                return ProviderOutput(
                    f"Grounded [{first.message_id}]",
                    (first.message_id,),
                    1.0,
                )

        provider = CaptureProvider()

        def no_memories(_dataset, _query, *, participant, limit):
            del participant, limit
            return []

        answer_about_person(
            self.dataset,
            "Is Carlos Juan's cousin or brother?",
            "Carlos",
            provider,
            memory_search=no_memories,
        )
        self.assertEqual(len(provider.evidence), 1)
        self.assertIn("Carlos", provider.evidence[0].excerpt)
        self.assertNotIn("Alice", provider.evidence[0].excerpt)


class TestCorrectionCLI(unittest.TestCase):
    def test_correct_requires_exactly_one_action(self):
        parser = build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["correct", "text", "--slug", "sample"])
        with self.assertRaises(SystemExit):
            parser.parse_args([
                "correct", "text", "--slug", "sample", "--dry-run", "--apply"
            ])


class TestCorrectionEndToEnd(unittest.TestCase):
    def test_import_correct_rebuild_answer_and_undo(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "knowledge"
            output = StringIO()
            correction = "Samantha is Alex's friend, not her conversation partner"
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
                previewed = main([
                    "correct", correction, "--slug", "sample", "--dry-run"
                ])
                applied = main([
                    "correct", correction, "--slug", "sample", "--apply"
                ])

            self.assertEqual((imported, previewed, applied), (0, 0, 0), output.getvalue())
            dataset = root / "sample"
            ledger_before_rebuild = dataset.joinpath("corrections", "ledger.jsonl").read_bytes()
            _entities, relationships, _stats = query_kg._load_kg(dataset)
            self.assertTrue(any(item["type"] == "friend_of" for item in relationships))
            self.assertFalse(any(item["type"] == "communicates_with" for item in relationships))

            from chromadb.api.client import SharedSystemClient

            SharedSystemClient.clear_system_cache()
            gc.collect()
            rebuild_all.rebuild_dataset(dataset, "sample", atomic=True)
            self.assertEqual(
                dataset.joinpath("corrections", "ledger.jsonl").read_bytes(),
                ledger_before_rebuild,
            )
            _entities, rebuilt, _stats = query_kg._load_kg(dataset)
            self.assertTrue(any(item["type"] == "friend_of" for item in rebuilt))
            self.assertFalse(any(item["type"] == "communicates_with" for item in rebuilt))

            answer = answer_about_person(
                dataset,
                "Is Samantha Alex's friend or conversation partner?",
                "Samantha",
                LocalExtractiveProvider(),
            )
            self.assertFalse(answer.abstained)
            self.assertEqual(answer.citations[0].source_type, "user_correction")
            self.assertIn("friend_of", answer.citations[0].excerpt)

            claim_id = correction_records(dataset)[0]["claim_id"]
            with patch.dict(os.environ, {"OPENPERSONA_KNOWLEDGE": str(root)}):
                undone = main([
                    "corrections", "--slug", "sample", "undo", claim_id
                ])
            self.assertEqual(undone, 0)
            _entities, restored, _stats = query_kg._load_kg(dataset)
            self.assertTrue(any(item["type"] == "communicates_with" for item in restored))
            self.assertFalse(any(item["type"] == "friend_of" for item in restored))

            SharedSystemClient.clear_system_cache()
            gc.collect()


if __name__ == "__main__":
    unittest.main()
