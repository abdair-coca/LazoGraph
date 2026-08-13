"""Tests for the Slice 6 plan domain and atomic derived projection."""

from datetime import datetime, timezone
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from lazograph.domain.plans import Plan, PlanValidationError
from lazograph.features.pending_plans import PlanProjectionError, load_projection, rebuild_projection


class PlanFoundationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dataset = Path(self.tmp.name) / "sample"
        self.sources = self.dataset / "sources"
        self.sources.mkdir(parents=True)
        self.sources.joinpath("chat.jsonl").write_text('{"content": "Dinner next week"}\n', encoding="utf-8")
        self.dataset.joinpath("dataset.json").write_text(json.dumps({"timezone": "America/La_Paz"}), encoding="utf-8")
        self.when = datetime(2026, 8, 13, 9, tzinfo=timezone.utc)

    def tearDown(self):
        self.tmp.cleanup()

    def _plan(self):
        return Plan.create("Dinner with Alex", ["Alex", "Sam"], self.when, ["chat.jsonl:4"], confidence=.8)

    def test_plan_id_and_transition_are_deterministic_and_provenanced(self):
        first = Plan.create("Dinner with Alex", ["Alex", "Sam"], self.when, ["chat.jsonl:4", "chat.jsonl:8"], confidence=.8)
        same = Plan.create(" dinner with alex ", ["Sam", "Alex"], self.when, ["chat.jsonl:8", "chat.jsonl:4"], confidence=.8)
        scheduled = first.transition("pending", self.when, ["chat.jsonl:8"], confidence=.9).transition("scheduled", self.when, ["chat.jsonl:12"], confidence=1, scheduled_for=self.when)
        self.assertEqual(first.id, same.id)
        self.assertEqual(scheduled.status, "scheduled")
        self.assertEqual(scheduled.transitions[-1].source_ids, ("chat.jsonl:12",))
        self.assertEqual(scheduled.source_ids, ("chat.jsonl:4", "chat.jsonl:8"))

    def test_unaware_dates_and_invalid_lifecycle_fail_closed(self):
        with self.assertRaisesRegex(PlanValidationError, "timezone-aware"):
            Plan.create("Dinner", [], datetime(2026, 8, 13), ["chat:1"], confidence=.5)
        with self.assertRaisesRegex(PlanValidationError, "Invalid plan transition"):
            self._plan().transition("completed", self.when, ["chat:9"], confidence=.9)

    def test_projection_replace_is_deterministic_and_does_not_mutate_sources(self):
        source_before = self.sources.joinpath("chat.jsonl").read_bytes()
        plan = self._plan()
        rebuild_projection(self.dataset, [plan])
        first = self.dataset.joinpath("plans", "projection.json").read_bytes()
        rebuild_projection(self.dataset, [plan])
        self.assertEqual(first, self.dataset.joinpath("plans", "projection.json").read_bytes())
        self.assertEqual(load_projection(self.dataset), [plan])
        self.assertEqual(self.sources.joinpath("chat.jsonl").read_bytes(), source_before)

    def test_missing_timezone_corruption_and_lock_fail_closed(self):
        self.dataset.joinpath("dataset.json").write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(PlanProjectionError, "IANA timezone"):
            rebuild_projection(self.dataset, [self._plan()])
        self.dataset.joinpath("dataset.json").write_text(json.dumps({"timezone": "UTC"}), encoding="utf-8")
        plans_dir = self.dataset / "plans"
        plans_dir.mkdir()
        plans_dir.joinpath("projection.json").write_text("not-json", encoding="utf-8")
        with self.assertRaisesRegex(PlanProjectionError, "corrupt"):
            load_projection(self.dataset)
        plans_dir.joinpath(".projection.lock").write_text("busy", encoding="utf-8")
        with self.assertRaisesRegex(PlanProjectionError, "locked"):
            rebuild_projection(self.dataset, [self._plan()])


if __name__ == "__main__":
    unittest.main()
