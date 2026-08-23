#!/usr/bin/env python3
"""Slice 7 grounded suggestion tests."""

import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from lazograph.cli import main
from lazograph.domain.answer import Answer, Evidence, ProviderOutput
from lazograph.domain.plans import Plan
from lazograph.features.pending_plans import rebuild_projection
from lazograph.features.suggestions import (
    answer_suggestion_question,
    is_suggestion_question,
    resolve_suggestion_participant,
)
from lazograph.infrastructure.llm import HostedProvider, LocalExtractiveProvider
from scripts import ingest


class SuggestionFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "knowledge"
        self.dataset = self.root / "sample"
        (self.dataset / "sources").mkdir(parents=True)
        self.dataset.joinpath("dataset.json").write_text(
            json.dumps({"slug": "sample", "name": "Samantha", "timezone": "UTC"}),
            encoding="utf-8",
        )
        self.profiles = [
            {"name": "Samantha", "aliases": ["Sam"], "identity_type": "persona"},
            {"name": "Alex", "aliases": ["Alexis"], "identity_type": "contact"},
        ]
        self.dataset.joinpath("participants.json").write_text(
            json.dumps({"participants": self.profiles}), encoding="utf-8"
        )
        self.messages = [
            self.message("Alex", "I love books and reading.", "2026-08-20T10:00:00+00:00"),
            self.message("Alex", "I enjoy coffee.", "2026-08-20T10:01:00+00:00"),
            self.message("Samantha", "Alex and I will meet for coffee.", "2026-08-20T10:02:00+00:00"),
        ]
        self.dataset.joinpath("sources", "chat.jsonl").write_text(
            "".join(json.dumps(item) + "\n" for item in self.messages), encoding="utf-8"
        )

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def message(sender, content, timestamp):
        return {
            "role": "user",
            "content": content,
            "timestamp": timestamp,
            "source_file": "chat.txt",
            "source_type": "whatsapp",
            "metadata": {"sender": sender},
        }

    def search(self, messages=None):
        messages = messages or self.messages[:2]

        def search(_dataset, _query, *, participant, limit):
            del participant
            return [
                {
                    "id": ingest._vector_id("sample", message),
                    "content": message["content"],
                    "metadata": {
                        "sender": message["metadata"]["sender"],
                        "authored_at": message["timestamp"],
                    },
                    "distance": 0.1,
                }
                for message in messages[:limit]
            ]

        return search

    def add_plan(self):
        plan = Plan.create(
            "coffee with Alex",
            ("Samantha", "Alex"),
            datetime(2026, 8, 20, 10, tzinfo=timezone.utc),
            ("chat.jsonl:3",),
            confidence=0.9,
        ).transition(
            "scheduled",
            datetime(2026, 8, 20, 10, 1, tzinfo=timezone.utc),
            ("chat.jsonl:3",),
            confidence=0.9,
            scheduled_for=datetime(2026, 8, 21, 10, tzinfo=timezone.utc),
        )
        rebuild_projection(self.dataset, [plan])

    def add_correction(self):
        corrections = self.dataset / "corrections"
        corrections.mkdir()
        corrections.joinpath("ledger.jsonl").write_text(
            json.dumps({
                "event_type": "correction",
                "event_id": "claim-gift",
                "claim_id": "claim-gift",
                "created_at": "2026-08-20T12:00:00+00:00",
                "raw_text": "Alex does not prefer gadgets",
                "retract": {"subject": "Alex", "predicate": "friend_of", "object": "Gadgets"},
                "assert": {"subject": "Alex", "predicate": "cousin_of", "object": "Books"},
            }) + "\n",
            encoding="utf-8",
        )


class TestSuggestionIdentity(SuggestionFixture):
    def test_alias_resolves_one_canonical_participant(self):
        self.assertEqual(resolve_suggestion_participant(self.dataset, "What gift for Alexis?")["name"], "Alex")

    def test_missing_target_fails_closed(self):
        answer = answer_suggestion_question(
            self.dataset, "What could I give as a gift?", LocalExtractiveProvider(), memory_search=self.search()
        )
        self.assertTrue(answer.abstained)
        self.assertEqual(answer.retrieval_summary["abstention_reason"], "unresolved_target")
        self.assertEqual(answer.entities, ())

    def test_ambiguous_target_fails_closed(self):
        self.profiles.append({"name": "Alex Rivera", "aliases": ["Alex"], "identity_type": "contact"})
        self.dataset.joinpath("participants.json").write_text(
            json.dumps({"participants": self.profiles}), encoding="utf-8"
        )
        answer = answer_suggestion_question(
            self.dataset, "What gift for Alex?", LocalExtractiveProvider(), memory_search=self.search()
        )
        self.assertTrue(answer.abstained)
        self.assertEqual(answer.retrieval_summary["abstention_reason"], "unresolved_target")


class TestSuggestionAnswer(SuggestionFixture):
    def test_english_and_spanish_intents(self):
        self.assertTrue(is_suggestion_question("What could I give Alex as a gift?"))
        self.assertTrue(is_suggestion_question("¿Qué podría regalarle Alex?"))

    def test_local_answer_has_separate_suggestions_and_citations(self):
        answer = answer_suggestion_question(
            self.dataset,
            "What could I give Alex as a gift?",
            LocalExtractiveProvider(),
            memory_search=self.search(),
        )
        self.assertFalse(answer.abstained)
        self.assertTrue(answer.suggestions)
        self.assertTrue(answer.missing_information)
        self.assertIn("book", answer.text.lower())
        for item in answer.citations:
            self.assertIn(f"[{item.message_id}]", answer.text)
        self.assertTrue(all(item.sender == "Alex" for item in answer.citations))

    def test_correction_and_active_plan_are_selected_and_cited(self):
        self.add_correction()
        self.add_plan()
        answer = answer_suggestion_question(
            self.dataset,
            "What could I give Alex as a gift?",
            LocalExtractiveProvider(),
            memory_search=self.search(),
        )
        ids = {item.message_id for item in answer.citations}
        self.assertIn("correction:claim-gift", ids)
        self.assertIn("chat.jsonl:3", ids)
        self.assertIn("active correction", answer.text)
        self.assertIn("active plan", answer.text)

    def test_active_plan_date_influences_cited_suggestion_context(self):
        self.add_plan()
        answer = answer_suggestion_question(
            self.dataset,
            "What could I give Alex as a gift?",
            LocalExtractiveProvider(),
            memory_search=self.search(),
        )
        self.assertIn("2026-08-21", answer.text)
        self.assertIn("[chat.jsonl:3]", answer.text)

    def test_insufficient_context_abstains(self):
        unrelated = [self.message("Alex", "The weather is warm.", "2026-08-20T10:00:00+00:00")]
        answer = answer_suggestion_question(
            self.dataset,
            "What could I give Alex as a gift?",
            LocalExtractiveProvider(),
            memory_search=self.search(unrelated),
        )
        self.assertTrue(answer.abstained)
        self.assertEqual(answer.retrieval_summary["abstention_reason"], "insufficient_relevant_evidence")

    def test_generic_preference_language_does_not_ground_suggestion(self):
        generic = [self.message("Alex", "Lo que te gusta", "2026-08-20T10:00:00+00:00")]
        answer = answer_suggestion_question(
            self.dataset,
            "¿Qué podría regalarle a Alex?",
            LocalExtractiveProvider(),
            memory_search=self.search(generic),
        )
        self.assertTrue(answer.abstained)
        self.assertEqual(answer.retrieval_summary["abstention_reason"], "insufficient_relevant_evidence")

    def test_sensitive_context_abstains(self):
        sensitive = [self.message("Alex", "Alex has a medical diagnosis.", "2026-08-20T10:00:00+00:00")]
        with self.dataset.joinpath("sources", "chat.jsonl").open("a", encoding="utf-8") as source:
            source.write(json.dumps(sensitive[0]) + "\n")
        answer = answer_suggestion_question(
            self.dataset,
            "What could I give Alex as a gift?",
            LocalExtractiveProvider(),
            memory_search=self.search(sensitive),
        )
        self.assertTrue(answer.abstained)
        self.assertEqual(answer.retrieval_summary["abstention_reason"], "sensitive_context")

    def test_suggestion_does_not_mutate_dataset(self):
        before = {path.relative_to(self.dataset): path.read_bytes() for path in self.dataset.rglob("*") if path.is_file()}
        answer_suggestion_question(
            self.dataset,
            "What could I give Alex as a gift?",
            LocalExtractiveProvider(),
            memory_search=self.search(),
        )
        after = {path.relative_to(self.dataset): path.read_bytes() for path in self.dataset.rglob("*") if path.is_file()}
        self.assertEqual(after, before)


class TestSuggestionProviderBoundary(unittest.TestCase):
    def test_hosted_payload_requests_structured_suggestions(self):
        evidence = Evidence("chat.jsonl:1", "Alex", "chat.jsonl", None, "Alex likes books.", .9)
        captured = {}

        def transport(_url, _headers, payload):
            captured["payload"] = payload
            return {"choices": [{"message": {"content": json.dumps({
                "text": "Suggestion: consider a book [chat.jsonl:1]",
                "citation_ids": ["chat.jsonl:1"],
                "confidence": .9,
                "abstained": False,
                "suggestions": ["Consider a book [chat.jsonl:1]"],
                "missing_information": ["budget"],
            })}}]}

        provider = HostedProvider(
            url="https://provider.invalid/chat", model="test", api_key="key", transport=transport
        )
        output = provider.generate("What gift?", "Alex", [evidence], {"answer_mode": "suggestions"}, language="en")
        self.assertEqual(output.suggestions, ("Consider a book [chat.jsonl:1]",))
        self.assertEqual(output.missing_information, ("budget",))
        self.assertIn("suggestions", captured["payload"]["messages"][0]["content"])
        self.assertIn("missing_information", captured["payload"]["messages"][0]["content"])

    def test_cli_routes_bilingual_suggestions_before_relationship_fallback(self):
        answer = Answer("suggestion", (), 1, ("Alex",), suggestions=("Suggestion",))
        with (
            patch("lazograph.cli.resolve_dataset"),
            patch("lazograph.cli.answer_suggestion_question", return_value=answer) as suggestion,
            patch("lazograph.cli.answer_about_relationship") as relationship,
            patch.dict(os.environ, {"OPENPERSONA_KNOWLEDGE": "unused"}),
            redirect_stdout(StringIO()), redirect_stderr(StringIO()),
        ):
            self.assertEqual(main(["ask", "What could I give Alex as a gift?", "--slug", "sample"]), 0)
            self.assertEqual(main(["ask", "¿Qué podría regalarle Alex?", "--slug", "sample"]), 0)
        self.assertEqual(suggestion.call_count, 2)
        relationship.assert_not_called()


if __name__ == "__main__":
    unittest.main()
