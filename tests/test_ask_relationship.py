#!/usr/bin/env python3
"""Slice 5 grounded relationship-question tests."""

import gc
import json
import os
import sqlite3
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
from lazograph.domain.answer import Answer, ProviderOutput
from lazograph.features.ask_relationship import (
    RelationshipQuestionError,
    answer_about_relationship,
    resolve_relationship_participants,
)
from lazograph.features.correct_knowledge import apply_correction, build_correction_preview
from lazograph.infrastructure.llm import HostedProvider, LocalExtractiveProvider


def no_memories(_dataset, _query, *, participant, limit):
    del participant, limit
    return []


class RecordingProvider:
    name = "recording"
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
        graph = next(item for item in evidence if item.record_kind == "effective_relationship")
        return ProviderOutput(
            text=f"Grounded relationship interpretation [{graph.message_id}]",
            citation_ids=(graph.message_id,),
            confidence=0.8,
        )


class RelationshipFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.tmp.name) / "knowledge"
        self.dataset = self.root / "sample"
        self.sources = self.dataset / "sources"
        self.sources.mkdir(parents=True)
        (self.dataset / "wiki").mkdir()
        (self.dataset / "wiki" / "relationships.md").write_text(
            "# Relationships\nSamantha and Alex appear in the relationship graph.\n",
            encoding="utf-8",
        )
        self.messages = [
            self.message("Samantha", "Hola Alex", "assistant", "2026-01-01T10:00:00", "chat.txt"),
            self.message("Alex", "Hola Samantha", "user", "2026-01-01T10:01:00", "chat.txt"),
            self.message(
                "Samantha",
                "Alex es mi pareja y hacemos planes juntos.",
                "assistant",
                "2026-02-02T12:00:00",
                "chat.txt",
            ),
            self.message("Alex", "Nos vemos mañana", "user", "2026-03-03T18:00:00", "chat.txt"),
            self.message("Jordan", "Trabajo en otro proyecto", "user", "2026-04-01T09:00:00", "other.txt"),
        ]
        self.sources.joinpath("chat.jsonl").write_text(
            "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in self.messages),
            encoding="utf-8",
        )
        self.dataset.joinpath("dataset.json").write_text(
            json.dumps({"slug": "sample", "name": "Samantha"}),
            encoding="utf-8",
        )
        self.profiles = [
            {
                "name": "Samantha",
                "aliases": ["Samantha", "Sam"],
                "identity_type": "persona",
                "first_seen": "2026-01-01T10:00:00",
                "last_seen": "2026-02-02T12:00:00",
            },
            {
                "name": "Alex",
                "aliases": ["Alex", "Alexis"],
                "identity_type": "contact",
                "first_seen": "2026-01-01T10:01:00",
                "last_seen": "2026-03-03T18:00:00",
            },
            {
                "name": "Jordan",
                "aliases": ["Jordan"],
                "identity_type": "contact",
                "first_seen": "2026-04-01T09:00:00",
                "last_seen": "2026-04-01T09:00:00",
            },
        ]
        self.write_profiles(self.profiles)
        self.relationships = [
            {
                "from": "Samantha",
                "to": "Alex",
                "type": "communicates_with",
                "confidence": 1.0,
                "timestamp": "2026-01-01",
                "source": "chat.txt",
                "claim_id": "base-communicates",
            },
            {
                "from": "Samantha",
                "to": "Alex",
                "type": "romantic_partner",
                "confidence": 0.95,
                "timestamp": "2026-02-02",
                "source": "chat.txt",
                "claim_id": "base-romantic",
            },
            {
                "from": "Jordan",
                "to": "sample",
                "type": "participant_in",
                "confidence": 1.0,
                "source": "other.txt",
            },
        ]

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def message(sender, content, role, timestamp, source_file):
        return {
            "role": role,
            "content": content,
            "timestamp": timestamp,
            "source_file": source_file,
            "source_type": "whatsapp",
            "metadata": {"sender": sender},
        }

    def write_profiles(self, profiles):
        self.dataset.joinpath("participants.json").write_text(
            json.dumps({"participants": profiles}), encoding="utf-8"
        )

    def graph_loader(self, _dataset, *, profiles):
        del profiles
        entities = {
            str(item.get("from")) for item in self.relationships
        } | {str(item.get("to")) for item in self.relationships}
        return entities, list(self.relationships), None


class TestRelationshipIdentity(RelationshipFixture):
    def test_aliases_resolve_to_canonical_participants(self):
        left, right = resolve_relationship_participants(
            self.dataset,
            "Who is Sam and how is she related to Alexis?",
        )
        self.assertEqual((left["name"], right["name"]), ("Samantha", "Alex"))

    def test_first_person_resolves_unique_focal_persona(self):
        left, right = resolve_relationship_participants(
            self.dataset,
            "¿Qué relación tengo yo con Alexis?",
        )
        self.assertEqual((left["name"], right["name"]), ("Samantha", "Alex"))

    def test_unique_first_name_prefix_resolves_canonical_identity(self):
        self.profiles[0]["name"] = "Samantha Rivera"
        self.profiles[0]["aliases"] = ["Samantha Rivera"]
        self.write_profiles(self.profiles)
        left, right = resolve_relationship_participants(
            self.dataset,
            "¿Qué relación tiene Samantha con Alex?",
        )
        self.assertEqual((left["name"], right["name"]), ("Samantha Rivera", "Alex"))

    def test_shared_name_prefix_is_ambiguous(self):
        self.profiles.append({
            "name": "Samantha Jones",
            "aliases": ["Samantha Jones"],
            "identity_type": "contact",
        })
        self.write_profiles(self.profiles)
        with self.assertRaisesRegex(RelationshipQuestionError, "ambiguous"):
            resolve_relationship_participants(
                self.dataset,
                "¿Qué relación tiene Samantha con Alex?",
            )

    def test_more_than_two_named_participants_is_rejected(self):
        with self.assertRaisesRegex(RelationshipQuestionError, "exactly two"):
            resolve_relationship_participants(
                self.dataset,
                "How are Samantha, Alex, and Jordan connected?",
            )


class TestRelationshipAnswer(RelationshipFixture):
    def answer(self, question="¿Quién es Samantha y qué relación tiene con Alex?", **kwargs):
        return answer_about_relationship(
            self.dataset,
            question,
            kwargs.pop("provider", LocalExtractiveProvider()),
            memory_search=kwargs.pop("memory_search", no_memories),
            graph_loader=kwargs.pop("graph_loader", self.graph_loader),
            **kwargs,
        )

    def test_direct_relationship_has_cited_facts_and_separate_interpretation(self):
        answer = self.answer()

        self.assertFalse(answer.abstained)
        self.assertEqual(answer.entities, ("Samantha", "Alex"))
        self.assertEqual(answer.retrieval_summary["kg_hops"], 1)
        self.assertEqual(len(answer.facts), 3)
        self.assertEqual(len(answer.inferences), 1)
        self.assertIn("Hechos:", answer.text)
        self.assertIn("Interpretación:", answer.text)
        for citation in answer.citations:
            self.assertIn(f"[{citation.message_id}]", answer.text)

    def test_temporal_fact_uses_first_and_last_endpoint_messages(self):
        answer = self.answer()

        self.assertIn("2026-01-01T10:00:00 — 2026-03-03T18:00:00", answer.facts[-1])
        self.assertIn("chat.jsonl:1", answer.facts[-1])
        self.assertIn("chat.jsonl:4", answer.facts[-1])

    def test_date_only_graph_timestamp_cites_message_from_same_day(self):
        answer = self.answer()
        romantic_fact = next(item for item in answer.facts if "pareja" in item)

        self.assertIn("chat.jsonl:3", romantic_fact)
        self.assertNotIn("chat.jsonl:1]", romantic_fact)

    def test_participant_membership_does_not_invent_relationship_path(self):
        answer = self.answer("¿Qué relación tiene Samantha con Jordan?")

        self.assertTrue(answer.abstained)
        self.assertEqual(
            answer.retrieval_summary["abstention_reason"],
            "no_supported_relationship_path",
        )
        self.assertEqual(answer.citations, ())

    def test_missing_original_support_causes_abstention(self):
        self.relationships[0]["source"] = "missing.txt"
        self.relationships = self.relationships[:1]
        answer = self.answer()

        self.assertTrue(answer.abstained)
        self.assertEqual(
            answer.retrieval_summary["abstention_reason"],
            "relationship_missing_source_evidence",
        )

    def test_provider_receives_only_path_participants(self):
        provider = RecordingProvider()

        def malicious_search(_dataset, _query, *, participant, limit):
            del participant, limit
            jordan = self.messages[-1]
            return [{
                "id": "unpersisted-jordan",
                "content": jordan["content"],
                "metadata": {
                    "sender": "Jordan",
                    "authored_at": jordan["timestamp"],
                },
                "distance": 0.01,
            }]

        answer = self.answer(provider=provider, memory_search=malicious_search, limit=10)

        self.assertFalse(answer.abstained)
        evidence = provider.calls[0]["evidence"]
        self.assertNotIn("Jordan", {item.sender for item in evidence})
        self.assertNotIn("otro proyecto", " ".join(item.excerpt for item in evidence))

    def test_structured_json_exposes_facts_inferences_and_path(self):
        payload = self.answer().to_dict()

        self.assertEqual(len(payload["facts"]), 3)
        self.assertEqual(len(payload["inferences"]), 1)
        self.assertEqual(payload["retrieval_summary"]["kg_path"], ["Samantha", "Alex"])

    def test_indirect_path_is_labeled_without_claiming_direct_relationship(self):
        maria = {
            "name": "Maria",
            "aliases": ["Maria"],
            "identity_type": "contact",
        }
        self.write_profiles([*self.profiles, maria])
        self.messages.extend([
            self.message("Maria", "Soy amiga de Samantha", "user", "2026-01-02T10:00:00", "a.txt"),
            self.message("Maria", "Soy amiga de Jordan", "user", "2026-01-03T10:00:00", "b.txt"),
        ])
        self.sources.joinpath("chat.jsonl").write_text(
            "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in self.messages),
            encoding="utf-8",
        )
        self.relationships = [
            {
                "from": "Samantha", "to": "Maria", "type": "friend_of",
                "confidence": 0.9, "timestamp": "2026-01-02", "source": "a.txt",
                "claim_id": "base-a",
            },
            {
                "from": "Maria", "to": "Jordan", "type": "friend_of",
                "confidence": 0.9, "timestamp": "2026-01-03", "source": "b.txt",
                "claim_id": "base-b",
            },
        ]

        answer = self.answer("How are Samantha and Jordan connected?", limit=6)

        self.assertFalse(answer.abstained)
        self.assertEqual(answer.retrieval_summary["kg_hops"], 2)
        self.assertIn("indirect", answer.inferences[0])
        self.assertEqual(len(answer.facts), 3)


class TestCorrectedRelationship(unittest.TestCase):
    def test_effective_correction_replaces_generated_relation_and_is_cited(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            dataset = Path(tmp) / "sample"
            sources = dataset / "sources"
            palace = dataset / ".mempalace" / "palace"
            sources.mkdir(parents=True)
            palace.mkdir(parents=True)
            messages = [
                RelationshipFixture.message(
                    "Carlos", "Hola Juan", "assistant", "2026-01-01T10:00:00", "chat.txt"
                ),
                RelationshipFixture.message(
                    "Juan", "Hola Carlos", "user", "2026-01-01T10:01:00", "chat.txt"
                ),
            ]
            sources.joinpath("chat.jsonl").write_text(
                "".join(json.dumps(item) + "\n" for item in messages), encoding="utf-8"
            )
            dataset.joinpath("dataset.json").write_text(
                json.dumps({"slug": "sample", "name": "Carlos"}), encoding="utf-8"
            )
            dataset.joinpath("participants.json").write_text(json.dumps({"participants": [
                {"name": "Carlos", "aliases": ["Carlitos"], "identity_type": "persona"},
                {"name": "Juan", "aliases": ["Juanito"], "identity_type": "contact"},
            ]}), encoding="utf-8")
            connection = sqlite3.connect(palace / "knowledge_graph.sqlite3")
            connection.execute("CREATE TABLE entities (id TEXT PRIMARY KEY, name TEXT)")
            connection.executemany(
                "INSERT INTO entities VALUES (?, ?)", [("1", "Carlos"), ("2", "Juan")]
            )
            connection.execute(
                "CREATE TABLE triples (subject TEXT, predicate TEXT, object TEXT, "
                "confidence REAL, source_file TEXT, valid_from TEXT)"
            )
            connection.execute(
                "INSERT INTO triples VALUES (?, ?, ?, ?, ?, ?)",
                ("1", "sibling_of", "2", 0.84, "chat.txt", "2026-01-01"),
            )
            connection.commit()
            connection.close()
            preview = build_correction_preview(
                "Carlitos no es hermano de Juanito, es su primo", dataset
            )
            apply_correction(preview)

            answer = answer_about_relationship(
                dataset,
                "¿Carlos es primo o hermano de Juan?",
                LocalExtractiveProvider(),
                memory_search=no_memories,
            )

            self.assertFalse(answer.abstained)
            self.assertEqual(answer.retrieval_summary["path_relationships"], ["cousin_of"])
            self.assertTrue(any(item.source_type == "user_correction" for item in answer.citations))
            self.assertIn("corrección del usuario", answer.facts[0])
            self.assertNotIn("hermano/a", answer.facts[0])


class TestRelationshipProviderBoundary(RelationshipFixture):
    def test_hosted_payload_contains_safe_path_and_selected_evidence_only(self):
        captured = {}

        def transport(url, headers, payload):
            captured.update({"url": url, "headers": headers, "payload": payload})
            content = json.dumps({
                "text": "Supported connection [graph:base-communicates]",
                "citation_ids": ["graph:base-communicates"],
                "confidence": 0.8,
                "abstained": False,
            })
            return {"choices": [{"message": {"content": content}}]}

        provider = HostedProvider(
            model="test-model",
            url="https://provider.invalid/v1/chat/completions",
            api_key="secret",
            transport=transport,
        )
        answer = answer_about_relationship(
            self.dataset,
            "How are Samantha and Alex related?",
            provider,
            memory_search=no_memories,
            graph_loader=self.graph_loader,
        )

        prompt = captured["payload"]["messages"][0]["content"]
        self.assertFalse(answer.abstained)
        self.assertIn("relationship_path", prompt)
        self.assertIn("graph:base-communicates", prompt)
        self.assertNotIn(str(self.dataset), prompt)
        self.assertNotIn("other project", prompt)


class TestRelationshipCLI(unittest.TestCase):
    def test_ask_without_about_routes_to_relationship_slice(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            (root / "sample").mkdir(parents=True)
            (root / "sample" / "dataset.json").write_text(
                json.dumps({"slug": "sample", "name": "Carlos"}),
                encoding="utf-8",
            )
            answer = Answer(
                text="Facts:\n- grounded",
                citations=(),
                confidence=0.8,
                entities=("Carlos", "Juan"),
                facts=("grounded",),
                inferences=(),
            )
            output = StringIO()
            with (
                patch.dict(os.environ, {"OPENPERSONA_KNOWLEDGE": str(root)}),
                patch("lazograph.cli.answer_about_relationship", return_value=answer) as routed,
                redirect_stdout(output),
                redirect_stderr(output),
            ):
                result = main(["ask", "How are Carlos and Juan related?", "--slug", "sample"])

            self.assertEqual(result, 0, output.getvalue())
            routed.assert_called_once()


class TestRelationshipEndToEnd(unittest.TestCase):
    def test_import_and_relationship_question_through_real_cli(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "knowledge"
            output = StringIO()
            with (
                patch.dict(os.environ, {"OPENPERSONA_KNOWLEDGE": str(root)}),
                redirect_stdout(output),
                redirect_stderr(output),
            ):
                imported = main([
                    "import",
                    str(ROOT / "tests" / "fixtures" / "sample-whatsapp-localized.txt"),
                    "--slug", "sample", "--persona", "Samantha", "--yes",
                ])
                asked = main([
                    "ask",
                    "Who is Samantha and how is she related to Alex?",
                    "--slug", "sample",
                    "--limit", "3",
                ])

            self.assertEqual((imported, asked), (0, 0), output.getvalue())
            self.assertIn("Facts:", output.getvalue())
            self.assertIn("communicates with", output.getvalue())
            self.assertIn("Interpretation:", output.getvalue())

            from chromadb.api.client import SharedSystemClient

            SharedSystemClient.clear_system_cache()
            gc.collect()


if __name__ == "__main__":
    unittest.main()
