"""Focused lifecycle tests for the bounded plan KG projection."""

import json
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from lazograph.domain.plans import Plan
from lazograph.features.pending_plans import PLAN_KG_ADAPTER, rebuild_kg_projection
from lazograph.features.pending_plans.extraction import rebuild_extracted_projection
from lazograph.features.ask_relationship.service import _relationship_graph


class SqliteGraph:
    def __init__(self, db_path):
        self.connection = sqlite3.connect(db_path)

    def add_entity(self, name, entity_type="unknown", properties=None):
        self.connection.execute(
            "INSERT OR IGNORE INTO entities (id, name, entity_type, properties) VALUES (?, ?, ?, ?)",
            (name, name, entity_type, json.dumps(properties or {}, sort_keys=True)),
        )
        self.connection.commit()

    def add_triple(self, **value):
        self.connection.execute(
            "INSERT INTO triples (subject, predicate, object, confidence, source_file, valid_from, adapter_name) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (value["subject"], value["predicate"], value["obj"], value["confidence"],
             value["source_file"], value["valid_from"], value["adapter_name"]),
        )
        self.connection.commit()

    def close(self):
        self.connection.close()


class FailingGraph(SqliteGraph):
    def add_triple(self, **value):
        raise RuntimeError("write failed")


class PlanKgProjectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dataset = Path(self.tmp.name) / "sample"
        self.db = self.dataset / ".mempalace" / "palace" / "knowledge_graph.sqlite3"
        self.db.parent.mkdir(parents=True)
        connection = sqlite3.connect(self.db)
        connection.execute(
            "CREATE TABLE entities (id TEXT PRIMARY KEY, name TEXT, entity_type TEXT, properties TEXT)"
        )
        connection.execute(
            "CREATE TABLE triples (id INTEGER PRIMARY KEY, subject TEXT, predicate TEXT, object TEXT, "
            "confidence REAL, source_file TEXT, valid_from TEXT, adapter_name TEXT)"
        )
        connection.execute(
            "INSERT INTO triples (subject, predicate, object, adapter_name) VALUES ('old', 'old', 'old', ?)",
            (PLAN_KG_ADAPTER,),
        )
        connection.execute(
            "INSERT INTO triples (subject, predicate, object, adapter_name) VALUES "
            "('Alex', 'friend_of', 'Sam', 'persona-knowledge'), "
            "('Alex', 'colleague_of', 'Sam', 'user-correction')"
        )
        connection.commit()
        connection.close()
        when = datetime(2026, 8, 13, 12, 0, tzinfo=ZoneInfo("America/La_Paz"))
        self.plan = Plan.create(
            "Coffee", ("Alex", "Sam"), when, ("chat.jsonl:7",), confidence=.9,
            location="Cafe Luna",
        ).transition("pending", when, ("chat.jsonl:8",), confidence=.95)

    def tearDown(self):
        self.tmp.cleanup()

    def rows(self):
        connection = sqlite3.connect(self.db)
        rows = connection.execute(
            "SELECT subject, predicate, object, source_file, adapter_name FROM triples ORDER BY id"
        ).fetchall()
        entities = connection.execute("SELECT name, entity_type FROM entities ORDER BY name").fetchall()
        connection.close()
        return rows, entities

    def test_rebuild_replaces_only_plan_edges_with_stable_source_backed_nodes(self):
        result = rebuild_kg_projection(self.dataset, [self.plan], graph_factory=SqliteGraph)
        rows, entities = self.rows()
        projected = [row for row in rows if row[-1] == PLAN_KG_ADAPTER]

        self.assertEqual(result, {"available": True, "plans": 1, "relationships": 3})
        self.assertEqual({row[1] for row in projected}, {"plan_participant", "plan_location"})
        self.assertEqual({row[0] for row in projected}, {f"plan:{self.plan.id}"})
        self.assertTrue(all(self.plan.id in row[3] and "chat.jsonl:7" in row[3] for row in projected))
        self.assertNotIn("pending", {value for row in rows for value in row if value})
        self.assertIn((f"plan:{self.plan.id}", "plan"), entities)
        self.assertEqual({row[-1] for row in rows}, {PLAN_KG_ADAPTER, "persona-knowledge", "user-correction"})

        rebuild_kg_projection(self.dataset, [self.plan], graph_factory=SqliteGraph)
        repeated, _ = self.rows()
        self.assertEqual(rows, repeated)

    def test_failed_rebuild_preserves_previous_database(self):
        before = self.rows()
        with self.assertRaisesRegex(RuntimeError, "write failed"):
            rebuild_kg_projection(self.dataset, [self.plan], graph_factory=FailingGraph)
        self.assertEqual(self.rows(), before)

    def test_extracted_projection_rebuild_invokes_kg_refresh(self):
        self.dataset.joinpath("dataset.json").write_text(
            json.dumps({"timezone": "America/La_Paz"}), encoding="utf-8"
        )
        self.dataset.joinpath("participants.json").write_text(
            json.dumps({"participants": []}), encoding="utf-8"
        )
        self.dataset.joinpath("sources").mkdir()
        with patch("lazograph.features.pending_plans.extraction.rebuild_kg_projection") as refresh:
            result = rebuild_extracted_projection(self.dataset)
        refresh.assert_called_once_with(self.dataset, result.plans)

    def test_plan_edges_do_not_become_relationship_answer_paths(self):
        relationships = [
            {"from": "Alex", "type": "friend_of", "to": "Sam", "authority": "user"},
            {"from": f"plan:{self.plan.id}", "type": "plan_participant", "to": "Alex"},
            {"from": f"plan:{self.plan.id}", "type": "plan_participant", "to": "Jordan"},
        ]
        _entities, usable = _relationship_graph(
            self.dataset, [], lambda *_args, **_kwargs: ({"Alex", "Sam", "Jordan"}, relationships, {}),
        )
        self.assertEqual(usable, [relationships[0]])


if __name__ == "__main__":
    unittest.main()
