#!/usr/bin/env python3
"""Slice 6 read-only plan interfaces and ask routing tests."""

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

from lazograph.cli import build_parser, main
from lazograph.domain.answer import Answer
from lazograph.domain.plans import Plan
from lazograph.features.pending_plans import answer_plan_question, rebuild_projection


class PlanInterfaceFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "knowledge"
        self.dataset = self.root / "sample"
        (self.dataset / "sources").mkdir(parents=True)
        self.dataset.joinpath("dataset.json").write_text(
            json.dumps({"slug": "sample", "name": "Samantha", "timezone": "UTC"}),
            encoding="utf-8",
        )
        messages = [
            {"content": "Let's have coffee with Alex", "timestamp": "2026-08-13T10:00:00+00:00", "metadata": {"sender": "Samantha"}},
            {"content": "Coffee is scheduled tomorrow", "timestamp": "2026-08-13T11:00:00+00:00", "metadata": {"sender": "Alex"}},
            {"content": "Dinner is done", "timestamp": "2026-08-14T11:00:00+00:00", "metadata": {"sender": "Alex"}},
        ]
        self.dataset.joinpath("sources", "chat.jsonl").write_text(
            "".join(json.dumps(item) + "\n" for item in messages), encoding="utf-8"
        )
        proposed = datetime(2026, 8, 13, 10, tzinfo=timezone.utc)
        self.coffee = Plan.create(
            "coffee", ("Samantha", "Alex"), proposed, ("chat.jsonl:1",), confidence=.8,
            location="Central Cafe",
        ).transition(
            "scheduled", datetime(2026, 8, 13, 11, tzinfo=timezone.utc),
            ("chat.jsonl:2",), confidence=.9,
            scheduled_for=datetime(2026, 8, 14, tzinfo=timezone.utc),
        )
        self.done = Plan.create(
            "dinner", ("Samantha",), proposed, ("chat.jsonl:3",), confidence=.8,
        ).transition(
            "pending", datetime(2026, 8, 13, 11, tzinfo=timezone.utc),
            ("chat.jsonl:3",), confidence=.9,
        ).transition(
            "completed", datetime(2026, 8, 14, 11, tzinfo=timezone.utc),
            ("chat.jsonl:3",), confidence=.9,
        )
        rebuild_projection(self.dataset, (self.coffee, self.done))

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, argv):
        output = StringIO()
        with (
            patch.dict(os.environ, {"OPENPERSONA_KNOWLEDGE": str(self.root)}),
            redirect_stdout(output), redirect_stderr(output),
        ):
            result = main(argv)
        return result, output.getvalue()


class TestPlanCLI(PlanInterfaceFixture):
    def test_parser_exposes_list_filters_and_show(self):
        listed = build_parser().parse_args([
            "plans", "list", "--slug", "sample", "--status", "scheduled",
            "--participant", "Alex", "--json",
        ])
        shown = build_parser().parse_args([
            "plans", "show", self.coffee.id, "--slug", "sample",
        ])
        self.assertEqual((listed.plan_command, shown.plan_command), ("list", "show"))

    def test_list_filters_and_show_render_source_backed_lifecycle(self):
        result, output = self.run_cli([
            "plans", "list", "--slug", "sample", "--status", "scheduled",
            "--participant", "alex", "--json",
        ])
        payload = json.loads(output)
        self.assertEqual(result, 0)
        self.assertEqual([item["id"] for item in payload], [self.coffee.id])

        result, output = self.run_cli([
            "plans", "show", self.coffee.id, "--slug", "sample",
        ])
        self.assertEqual(result, 0)
        self.assertIn("proposed -> scheduled", output)
        self.assertIn("chat.jsonl:2", output)

    def test_list_and_show_do_not_mutate_projection(self):
        before = {path.relative_to(self.dataset): path.read_bytes() for path in self.dataset.rglob("*") if path.is_file()}
        self.run_cli(["plans", "list", "--slug", "sample"])
        self.run_cli(["plans", "show", self.coffee.id, "--slug", "sample"])
        after = {path.relative_to(self.dataset): path.read_bytes() for path in self.dataset.rglob("*") if path.is_file()}
        self.assertEqual(after, before)

    def test_unknown_plan_fails_without_fallback(self):
        result, output = self.run_cli(["plans", "show", "plan-missing", "--slug", "sample"])
        self.assertEqual(result, 2)
        self.assertIn("Plan not found", output)


class TestPlanAskRouting(PlanInterfaceFixture):
    def test_pending_question_cites_creation_and_latest_transition(self):
        answer = answer_plan_question(self.dataset, "Do we have any pending plans?")
        self.assertEqual([item.message_id for item in answer.citations], ["chat.jsonl:1", "chat.jsonl:2"])
        self.assertIn("[chat.jsonl:1]", answer.text)
        self.assertIn("[chat.jsonl:2]", answer.text)
        self.assertNotIn("dinner", answer.text)

    def test_plan_route_precedes_relationship_fallback_but_about_stays_person(self):
        answer = Answer("plan answer", (), 1, ())
        with (
            patch("lazograph.cli.resolve_dataset", return_value=self.dataset),
            patch("lazograph.cli.answer_plan_question", return_value=answer) as plan_route,
            patch("lazograph.cli.answer_about_relationship") as relationship_route,
        ):
            result = main(["ask", "Do we have any pending plans?", "--slug", "sample"])
        self.assertEqual(result, 0)
        plan_route.assert_called_once()
        relationship_route.assert_not_called()

        with (
            patch("lazograph.cli.resolve_dataset", return_value=self.dataset),
            patch("lazograph.cli.answer_about_person", return_value=answer) as person_route,
            patch("lazograph.cli.answer_plan_question") as plan_route,
        ):
            result = main(["ask", "Any pending plans?", "--about", "Alex", "--slug", "sample"])
        self.assertEqual(result, 0)
        person_route.assert_called_once()
        plan_route.assert_not_called()

    def test_two_person_question_stays_relationship_route(self):
        answer = Answer("relationship", (), 1, ("Samantha", "Alex"))
        with (
            patch("lazograph.cli.resolve_dataset", return_value=self.dataset),
            patch("lazograph.cli.answer_about_relationship", return_value=answer) as routed,
            patch("lazograph.cli.answer_plan_question") as plan_route,
        ):
            result = main(["ask", "How are Samantha and Alex related?", "--slug", "sample"])
        self.assertEqual(result, 0)
        routed.assert_called_once()
        plan_route.assert_not_called()


if __name__ == "__main__":
    unittest.main()
