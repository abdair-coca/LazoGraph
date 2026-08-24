#!/usr/bin/env python3
"""Slice 2 grounded ask-about-person tests."""

import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from lazograph.cli import main
from lazograph.domain.answer import Answer, Evidence, ProviderOutput
from lazograph.features.ask_person.service import GroundingError, answer_about_person
from lazograph.infrastructure.llm import (
    HostedProvider,
    LocalExtractiveProvider,
    ProviderError,
)
from scripts import ingest


class FakeProvider:
    name = "fake"
    hosted = False

    def __init__(self):
        self.calls = []

    def generate(self, question, participant, evidence, context, *, language):
        self.calls.append({
            "question": question,
            "participant": participant,
            "evidence": list(evidence),
            "context": context,
            "language": language,
        })
        first = evidence[0]
        return ProviderOutput(
            text=f"Grounded fact [{first.message_id}]",
            citation_ids=(first.message_id,),
            confidence=0.8,
        )


class TestAskAboutPerson(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "knowledge"
        self.dataset = self.root / "sample"
        self.sources = self.dataset / "sources"
        self.sources.mkdir(parents=True)
        (self.dataset / "wiki").mkdir()
        (self.dataset / "wiki" / "values.md").write_text("# Values\n", encoding="utf-8")
        self.messages = [
            self._message("Samantha", "Me gusta pintar paisajes los domingos.", "assistant", 1),
            self._message("Samantha", "Trabajo en un proyecto de grafos.", "assistant", 2),
            self._message("Samantha", "Prefiero café sin azúcar.", "assistant", 3),
            self._message("Alex", "Mi color favorito es azul.", "user", 4),
            self._message("Alex", "Me gusta bailar salsa.", "user", 5),
        ]
        self.sources.joinpath("chat.jsonl").write_text(
            "".join(json.dumps(message, ensure_ascii=False) + "\n" for message in self.messages),
            encoding="utf-8",
        )
        self.dataset.joinpath("dataset.json").write_text(
            json.dumps({"slug": "sample", "name": "Samantha"}),
            encoding="utf-8",
        )
        self.dataset.joinpath("participants.json").write_text(
            json.dumps({
                "participants": [
                    {
                        "name": "Samantha",
                        "aliases": ["Samantha", "Sam"],
                        "identity_type": "persona",
                        "message_count": 3,
                        "first_seen": "2026-01-01T10:01:00",
                        "last_seen": "2026-01-01T10:03:00",
                    },
                    {
                        "name": "Alex",
                        "aliases": ["Alex", "Alexis"],
                        "identity_type": "contact",
                        "message_count": 2,
                    },
                ],
            }),
            encoding="utf-8",
        )

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def _message(sender, content, role, minute):
        return {
            "role": role,
            "content": content,
            "timestamp": f"2026-01-01T10:{minute:02d}:00",
            "source_file": "chat.txt",
            "source_type": "whatsapp",
            "metadata": {"sender": sender},
        }

    def _result(self, message, *, distance=0.1):
        return {
            "id": ingest._vector_id("sample", message),
            "content": message["content"],
            "metadata": {
                "sender": message["metadata"]["sender"],
                "authored_at": message["timestamp"],
            },
            "distance": distance,
        }

    def _search(self, messages):
        results = [self._result(message) for message in messages]

        def search(_dataset, _query, *, participant, limit):
            del participant
            return results[:limit]

        return search

    def test_spanish_question_returns_spanish_grounded_answer(self):
        answer = answer_about_person(
            self.dataset,
            "¿Qué le gusta a Samantha?",
            "Samantha",
            LocalExtractiveProvider(),
            memory_search=self._search(self.messages[:3]),
        )

        self.assertFalse(answer.abstained)
        self.assertTrue(answer.text.startswith("Según mensajes de Samantha"))
        self.assertGreaterEqual(len(answer.citations), 1)
        self.assertTrue(all(item.sender == "Samantha" for item in answer.citations))

    def test_sender_filter_is_applied_before_generation_and_rechecked(self):
        provider = FakeProvider()
        answer = answer_about_person(
            self.dataset,
            "¿Qué le gusta a Samantha?",
            "Sam",
            provider,
            memory_search=self._search([self.messages[4], self.messages[0]]),
        )

        self.assertEqual(provider.calls[0]["participant"], "Samantha")
        self.assertEqual([item.sender for item in provider.calls[0]["evidence"]], ["Samantha"])
        self.assertEqual(answer.retrieval_summary["rejected_sender"], 1)
        self.assertNotIn("bailar salsa", answer.text)

    def test_alias_and_canonical_queries_use_same_evidence(self):
        kwargs = {
            "provider": LocalExtractiveProvider(),
            "memory_search": self._search(self.messages[:3]),
        }
        canonical = answer_about_person(
            self.dataset, "¿Qué le gusta?", "Samantha", **kwargs
        )
        alias = answer_about_person(self.dataset, "¿Qué le gusta?", "Sam", **kwargs)

        self.assertEqual(
            [item.message_id for item in canonical.citations],
            [item.message_id for item in alias.citations],
        )

    def test_unknown_specific_preference_abstains(self):
        provider = FakeProvider()
        answer = answer_about_person(
            self.dataset,
            "¿Cuál es el color favorito de Samantha?",
            "Samantha",
            provider,
            memory_search=self._search(self.messages[:3]),
        )

        self.assertTrue(answer.abstained)
        self.assertEqual(answer.citations, ())
        self.assertEqual(provider.calls, [])
        self.assertIn("evidencia suficiente", answer.text)

    def test_contradictory_specific_preferences_abstain(self):
        positive = self._message("Samantha", "Me gusta el café.", "assistant", 6)
        negative = self._message("Samantha", "No me gusta el café.", "assistant", 7)
        with self.sources.joinpath("chat.jsonl").open("a", encoding="utf-8") as source:
            source.write(json.dumps(positive, ensure_ascii=False) + "\n")
            source.write(json.dumps(negative, ensure_ascii=False) + "\n")
        provider = FakeProvider()

        answer = answer_about_person(
            self.dataset,
            "¿Le gusta el café a Samantha?",
            "Samantha",
            provider,
            memory_search=self._search([positive, negative]),
        )

        self.assertTrue(answer.abstained)
        self.assertEqual(answer.retrieval_summary["abstention_reason"], "contradictory_evidence")
        self.assertEqual(provider.calls, [])

    def test_citations_resolve_to_persisted_source_lines(self):
        answer = answer_about_person(
            self.dataset,
            "¿En qué proyecto trabaja Samantha?",
            "Samantha",
            LocalExtractiveProvider(),
            memory_search=self._search([self.messages[1]]),
        )

        evidence = answer.citations[0]
        filename, line_number = evidence.message_id.rsplit(":", 1)
        persisted = self.dataset.joinpath("sources", filename).read_text(encoding="utf-8").splitlines()
        message = json.loads(persisted[int(line_number) - 1])
        self.assertEqual(message["content"], evidence.excerpt)
        self.assertEqual(message["metadata"]["sender"], evidence.sender)

    def test_spanish_inflections_use_same_relevance_rule(self):
        answer = answer_about_person(
            self.dataset,
            "¿Trabaja Samantha?",
            "Samantha",
            LocalExtractiveProvider(),
            memory_search=self._search([self.messages[1]]),
        )

        self.assertFalse(answer.abstained)
        self.assertIn("Trabajo en un proyecto", answer.text)

    def test_provider_cannot_cite_unselected_evidence(self):
        class InvalidProvider(FakeProvider):
            def generate(self, *args, **kwargs):
                return ProviderOutput("Invented [missing:99]", ("missing:99",), 1.0)

        with self.assertRaisesRegex(GroundingError, "unavailable evidence"):
            answer_about_person(
                self.dataset,
                "¿En qué proyecto trabaja Samantha?",
                "Samantha",
                InvalidProvider(),
                memory_search=self._search([self.messages[1]]),
            )

    def test_provider_must_put_citation_marker_in_answer(self):
        class MissingMarkerProvider(FakeProvider):
            def generate(self, question, participant, evidence, context, *, language):
                del question, participant, context, language
                return ProviderOutput("Grounded but marker missing", (evidence[0].message_id,), 0.7)

        with self.assertRaisesRegex(GroundingError, "omitted citation markers"):
            answer_about_person(
                self.dataset,
                "¿En qué proyecto trabaja Samantha?",
                "Samantha",
                MissingMarkerProvider(),
                memory_search=self._search([self.messages[1]]),
            )

    def test_fake_provider_receives_safe_enrichment(self):
        provider = FakeProvider()
        answer_about_person(
            self.dataset,
            "¿En qué proyecto trabaja Samantha?",
            "Samantha",
            provider,
            memory_search=self._search([self.messages[1]]),
        )

        context = provider.calls[0]["context"]
        self.assertEqual(context["identity_type"], "persona")
        self.assertEqual(context["wiki_pages"], ["values"])
        self.assertEqual(context["relationship_types"], [])

    def test_ask_does_not_mutate_dataset(self):
        before = {
            path.relative_to(self.dataset): path.read_bytes()
            for path in self.dataset.rglob("*") if path.is_file()
        }
        answer_about_person(
            self.dataset,
            "¿Qué le gusta a Samantha?",
            "Samantha",
            LocalExtractiveProvider(),
            memory_search=self._search(self.messages[:3]),
        )
        after = {
            path.relative_to(self.dataset): path.read_bytes()
            for path in self.dataset.rglob("*") if path.is_file()
        }
        self.assertEqual(after, before)

    def test_evidence_budget_caps_first_excerpt(self):
        long_message = self._message(
            "Samantha",
            "Me gusta pintar " + ("paisajes " * 80),
            "assistant",
            8,
        )
        with self.sources.joinpath("chat.jsonl").open("a", encoding="utf-8") as source:
            source.write(json.dumps(long_message, ensure_ascii=False) + "\n")

        answer = answer_about_person(
            self.dataset,
            "¿Qué le gusta a Samantha?",
            "Samantha",
            LocalExtractiveProvider(),
            evidence_budget=100,
            memory_search=self._search([long_message]),
        )

        self.assertLessEqual(len(answer.citations[0].excerpt), 100)
        self.assertLessEqual(answer.retrieval_summary["evidence_chars"], 100)


class TestHostedProviderPolicy(unittest.TestCase):
    def test_hosted_payload_contains_only_selected_evidence(self):
        captured = {}
        selected = Evidence(
            "chat.jsonl:1",
            "Samantha",
            "chat.jsonl",
            "2026-01-01T10:00:00",
            "Me gusta pintar.",
            0.9,
        )

        def transport(url, headers, payload):
            captured.update({"url": url, "headers": headers, "payload": payload})
            content = json.dumps({
                "text": "Le gusta pintar [chat.jsonl:1]",
                "citation_ids": ["chat.jsonl:1"],
                "confidence": 0.9,
                "abstained": False,
            })
            return {"choices": [{"message": {"content": content}}]}

        provider = HostedProvider(
            url="https://provider.invalid/chat",
            model="test-model",
            api_key="test-key",
            transport=transport,
        )
        output = provider.generate(
            "¿Qué le gusta?",
            "Samantha",
            [selected],
            {"identity_type": "persona", "unrelated_private_content": "Alex secret"},
            language="es",
        )

        serialized = json.dumps(captured["payload"], ensure_ascii=False)
        self.assertIn("Me gusta pintar", serialized)
        self.assertNotIn("Alex secret", serialized)
        self.assertNotIn("unrelated_private_content", serialized)
        self.assertEqual(output.citation_ids, ("chat.jsonl:1",))
        self.assertEqual(captured["headers"]["Authorization"], "Bearer test-key")

    def test_hosted_provider_requires_explicit_configuration(self):
        provider = HostedProvider(url="", model="", api_key="")
        with self.assertRaisesRegex(ProviderError, "requires"):
            provider.generate("Question", "Sam", [], {}, language="en")


class TestAskCLI(unittest.TestCase):
    def test_single_named_person_question_routes_to_person_answer(self):
        answer = Answer("person", (), 1.0, ("Alizon",))
        with (
            patch("lazograph.cli.resolve_dataset", return_value=Path("dataset")),
            patch("lazograph.cli.resolve_question_participant", return_value={"name": "Alizon"}),
            patch("lazograph.cli.answer_about_person", return_value=answer) as person_route,
            patch("lazograph.cli.answer_about_relationship") as relationship_route,
            redirect_stdout(StringIO()),
        ):
            result = main(["ask", "¿Qué cosas le gustan a Alizon?", "--slug", "sample"])

        self.assertEqual(result, 0)
        person_route.assert_called_once()
        relationship_route.assert_not_called()

    def test_general_question_routes_to_dataset_answer(self):
        answer = Answer("Facts", (), 1.0, ())
        with (
            patch("lazograph.cli.resolve_dataset", return_value=Path("dataset")),
            patch("lazograph.cli.resolve_question_participant", return_value=None),
            patch("lazograph.cli.answer_about_dataset", return_value=answer) as general_route,
            patch("lazograph.cli.answer_about_relationship") as relationship_route,
            redirect_stdout(StringIO()),
        ):
            result = main(["ask", "¿De qué hablamos?", "--slug", "sample"])

        self.assertEqual(result, 0)
        general_route.assert_called_once()
        relationship_route.assert_not_called()

    def test_provider_failure_returns_clear_nonzero_exit(self):
        with (
            patch("lazograph.cli.resolve_dataset", return_value=Path("dataset")),
            patch("lazograph.cli.answer_about_person", side_effect=ProviderError("offline")),
        ):
            result = main(["ask", "Question", "--about", "Sam"])
        self.assertEqual(result, 2)

    def test_multiple_datasets_require_slug(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("one", "two"):
                dataset = root / name
                dataset.mkdir()
                dataset.joinpath("dataset.json").write_text("{}", encoding="utf-8")
            with patch.dict(os.environ, {"OPENPERSONA_KNOWLEDGE": str(root)}):
                result = main(["ask", "Question", "--about", "Sam"])
        self.assertEqual(result, 2)

    def test_slug_cannot_escape_knowledge_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"OPENPERSONA_KNOWLEDGE": tmp}):
                result = main([
                    "ask",
                    "Question",
                    "--about",
                    "Sam",
                    "--slug",
                    "../outside",
                ])
        self.assertEqual(result, 2)


if __name__ == "__main__":
    unittest.main()
