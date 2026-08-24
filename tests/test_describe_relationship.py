#!/usr/bin/env python3
"""Slice 8 time-bounded relationship-description tests."""

import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from lazograph.cli import main
from lazograph.domain.answer import Answer, Evidence, ProviderOutput
from lazograph.features.describe_relationship import (
    answer_describe_relationship,
    is_relationship_description_question,
)
from lazograph.infrastructure.llm import HostedProvider, LocalExtractiveProvider


def no_memories(_dataset, _query, *, participant, limit):
    del participant, limit
    return []


class DescriptionFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dataset = Path(self.tmp.name) / "knowledge" / "sample"
        (self.dataset / "sources").mkdir(parents=True)
        self.dataset.joinpath("dataset.json").write_text(
            json.dumps({"slug": "sample", "name": "Samantha"}), encoding="utf-8"
        )
        self.profiles = [
            {"name": "Samantha", "aliases": ["Sam"], "identity_type": "persona"},
            {"name": "Alex", "aliases": ["Alexis"], "identity_type": "contact"},
        ]
        self.dataset.joinpath("participants.json").write_text(
            json.dumps({"participants": self.profiles}), encoding="utf-8"
        )
        self.messages = [
            self.message("Samantha", "Alex and I are close friends.", "2026-01-01T10:00:00"),
            self.message("Alex", "I appreciate Samantha and our friendship.", "2026-02-01T10:00:00"),
            self.message("Samantha", "We argued about the plan yesterday.", "2026-03-01T10:00:00"),
            self.message("Alex", "I do not like how that conversation ended.", "2026-04-01T10:00:00"),
        ]
        self.dataset.joinpath("sources", "chat.jsonl").write_text(
            "".join(json.dumps(item) + "\n" for item in self.messages), encoding="utf-8"
        )
        self.relationships = [{
            "from": "Samantha",
            "to": "Alex",
            "type": "friend_of",
            "confidence": 0.9,
            "timestamp": "2026-01-01",
            "source": "chat.txt",
            "claim_id": "friend-1",
        }]

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

    def graph_loader(self, _dataset, *, profiles):
        del profiles
        return {"Samantha", "Alex"}, list(self.relationships), None

    def answer(self, question="How would you describe my relationship with Alex?", **kwargs):
        return answer_describe_relationship(
            self.dataset,
            question,
            kwargs.pop("provider", LocalExtractiveProvider()),
            memory_search=kwargs.pop("memory_search", no_memories),
            graph_loader=kwargs.pop("graph_loader", self.graph_loader),
            **kwargs,
        )


class TestDescriptionRouting(unittest.TestCase):
    def test_bilingual_description_intent(self):
        self.assertTrue(is_relationship_description_question("How would you describe my relationship with Alex?"))
        self.assertTrue(is_relationship_description_question("¿Cómo describirías mi relación con Alex?"))
        self.assertFalse(is_relationship_description_question("How are Alex and Sam related?"))

    def test_cli_routes_description_before_single_person_fallback(self):
        answer = Answer("description", (), 0.8, ("Samantha", "Alex"))
        with (
            patch("lazograph.cli.resolve_dataset", return_value=Path("dataset")),
            patch("lazograph.cli.answer_describe_relationship", return_value=answer) as described,
            patch("lazograph.cli.answer_about_person") as person,
            redirect_stdout(StringIO()),
            redirect_stderr(StringIO()),
        ):
            result = main(["ask", "How would you describe my relationship with Alex?", "--slug", "sample"])
        self.assertEqual(result, 0)
        described.assert_called_once()
        person.assert_not_called()


class TestDescriptionAnswer(DescriptionFixture):
    def test_time_range_coverage_balanced_evidence_and_separation(self):
        answer = self.answer()

        self.assertFalse(answer.abstained)
        self.assertEqual(answer.entities, ("Samantha", "Alex"))
        self.assertIn("2026-01-01T10:00:00 — 2026-04-01T10:00:00", answer.text)
        self.assertIn("coverage: 4 persisted messages", answer.text)
        self.assertIn("Observations:", answer.text)
        self.assertIn("Positive observation", answer.text)
        self.assertIn("Negative observation", answer.text)
        self.assertIn("Contradictory evidence", answer.text)
        self.assertIn("Interpretation:", answer.text)
        self.assertTrue(answer.retrieval_summary["contradictory_evidence"])
        self.assertEqual(answer.retrieval_summary["evidence_coverage"]["messages"], 4)
        for item in answer.citations:
            self.assertIn(f"[{item.message_id}]", answer.text)

    def test_unsafe_diagnostic_request_abstains_without_provider_call(self):
        class FailingProvider(LocalExtractiveProvider):
            def generate(self, *args, **kwargs):
                raise AssertionError("provider must not receive diagnostic request")

        answer = self.answer("Is Alex narcissistic, and what does that say about our relationship?", provider=FailingProvider())

        self.assertTrue(answer.abstained)
        self.assertEqual(answer.retrieval_summary["abstention_reason"], "unsafe_diagnostic_language")
        self.assertIn("clinical", answer.text.lower())

    def test_active_correction_is_in_effective_summary(self):
        self.relationships = [{
            **self.relationships[0],
            "type": "cousin_of",
            "authority": "user",
            "claim_id": "claim-assert",
        }]
        answer = self.answer()

        self.assertFalse(answer.abstained)
        self.assertIn("Active user correction", answer.text)
        self.assertIn("[graph:claim-assert]", answer.text)

    def test_unsafe_provider_interpretation_is_rejected(self):
        class UnsafeProvider:
            name = "unsafe-test"
            hosted = False

            def generate(self, question, participant, evidence, context, *, language):
                del question, participant, context, language
                return ProviderOutput(
                    "Alex is narcissistic [graph:friend-1]",
                    (evidence[0].message_id,),
                    0.9,
                )

        answer = self.answer(provider=UnsafeProvider())

        self.assertTrue(answer.abstained)
        self.assertEqual(answer.retrieval_summary["abstention_reason"], "unsafe_provider_output")


class TestDescriptionProviderBoundary(unittest.TestCase):
    def test_hosted_payload_contains_only_selected_participants_and_safe_metadata(self):
        captured = {}

        def transport(_url, _headers, payload):
            captured["payload"] = payload
            content = json.dumps({
                "text": "Cautious interpretation [chat.jsonl:1]",
                "citation_ids": ["chat.jsonl:1"],
                "confidence": 0.8,
                "abstained": False,
            })
            return {"choices": [{"message": {"content": content}}]}

        provider = HostedProvider(
            url="https://provider.invalid/chat",
            model="test",
            api_key="secret",
            transport=transport,
        )
        evidence = [Evidence("chat.jsonl:1", "Alex", "chat.jsonl", None, "Alex appreciates Sam.", .9)]
        output = provider.generate(
            "Describe relationship",
            "Samantha ↔ Alex",
            evidence,
            {
                "answer_mode": "relationship_description",
                "evidence_coverage": {"messages": 1, "sources": 1},
                "unrelated_private_content": "Jordan secret",
            },
            language="en",
        )

        prompt = captured["payload"]["messages"][0]["content"]
        self.assertEqual(output.citation_ids, ("chat.jsonl:1",))
        self.assertIn("Alex appreciates Sam", prompt)
        self.assertIn("evidence_coverage", prompt)
        self.assertNotIn("Jordan secret", prompt)
        self.assertNotIn("unrelated_private_content", prompt)


if __name__ == "__main__":
    unittest.main()
