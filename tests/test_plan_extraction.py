"""Focused source-backed plan extraction tests for Slice 6 work unit 2."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from lazograph.features.pending_plans import extract_plans, load_projection, rebuild_extracted_projection


class PlanExtractionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dataset = Path(self.tmp.name) / "sample"
        self.sources = self.dataset / "sources"
        self.sources.mkdir(parents=True)
        self.dataset.joinpath("dataset.json").write_text(
            json.dumps({"timezone": "America/La_Paz"}), encoding="utf-8"
        )
        self.dataset.joinpath("participants.json").write_text(json.dumps({"participants": [
            {"name": "Samantha", "aliases": ["Sam"], "identity_type": "persona"},
            {"name": "Alex Rivera", "aliases": ["Alex"], "identity_type": "contact"},
            {"name": "Jordan Lee", "aliases": ["Jordan"], "identity_type": "contact"},
        ]}), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, messages):
        self.sources.joinpath("chat.jsonl").write_text(
            "".join(json.dumps(message) + "\n" for message in messages), encoding="utf-8"
        )

    @staticmethod
    def message(sender, content, timestamp):
        return {"content": content, "timestamp": timestamp, "metadata": {"sender": sender}}

    def test_reschedule_and_completion_keep_all_transition_evidence(self):
        self.write([
            self.message("Samantha", "Let's have dinner with Alex tomorrow at Cafe Luna.", "2026-08-13T02:30:00+00:00"),
            self.message("Alex", "Dinner with Sam was moved to Friday.", "2026-08-13T18:00:00+00:00"),
            self.message("Alex", "Dinner with Sam is done.", "2026-08-14T23:00:00+00:00"),
        ])

        result = extract_plans(self.dataset)

        self.assertEqual(len(result.unresolved), 0)
        plan = result.plans[0]
        self.assertEqual(plan.participants, ("Alex Rivera", "Samantha"))
        self.assertEqual((plan.status, plan.location), ("completed", "Cafe Luna"))
        self.assertEqual(plan.scheduled_for.date().isoformat(), "2026-08-14")
        self.assertEqual([item.to_status for item in plan.transitions], ["scheduled", "pending", "scheduled", "completed"])
        self.assertEqual(plan.transitions[-1].source_ids, ("chat.jsonl:3",))
        source_before = self.sources.joinpath("chat.jsonl").read_bytes()
        persisted = rebuild_extracted_projection(self.dataset)
        self.assertEqual(load_projection(self.dataset), list(persisted.plans))
        self.assertEqual(self.sources.joinpath("chat.jsonl").read_bytes(), source_before)

    def test_bilingual_pending_and_cancelled_plans_are_extracted(self):
        self.write([
            self.message("Samantha", "Vamos a tomar café con Alex mañana.", "2026-08-13T12:00:00-04:00"),
            self.message("Samantha", "We have a pending coffee with Alex.", "2026-08-13T12:00:30-04:00"),
            self.message("Samantha", "Let's have lunch with Jordan tomorrow.", "2026-08-13T12:01:00-04:00"),
            self.message("Jordan", "Lunch with Sam is cancelled.", "2026-08-13T13:00:00-04:00"),
        ])

        result = extract_plans(self.dataset)

        self.assertEqual(sorted(plan.status for plan in result.plans), ["cancelled", "pending", "scheduled"])
        cancelled = next(plan for plan in result.plans if plan.status == "cancelled")
        self.assertEqual(cancelled.transitions[-1].source_ids, ("chat.jsonl:4",))

    def test_ambiguous_title_only_update_never_mutates_a_plan(self):
        self.write([
            self.message("Samantha", "Let's have dinner tomorrow.", "2026-08-13T10:00:00-04:00"),
            self.message("Alex", "Let's have dinner tomorrow.", "2026-08-13T10:01:00-04:00"),
            self.message("Unknown", "Dinner is cancelled.", "2026-08-13T11:00:00-04:00"),
        ])

        result = extract_plans(self.dataset)

        self.assertEqual([plan.status for plan in result.plans], ["scheduled", "scheduled"])
        self.assertEqual(result.unresolved[-1].reason, "ambiguous_lifecycle_match")
        self.assertEqual(result.unresolved[-1].source_ids, ("chat.jsonl:3",))


if __name__ == "__main__":
    unittest.main()
