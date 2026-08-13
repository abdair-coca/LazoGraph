"""Bounded, source-backed Knowledge Graph projection for plans."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Callable, Iterable

from lazograph.domain.plans import Plan


PLAN_KG_ADAPTER = "lazograph-plans"


def _node(plan: Plan) -> str:
    return f"plan:{plan.id}"


def _source(plan: Plan) -> str:
    return json.dumps(
        {"plan_id": plan.id, "source_ids": list(plan.source_ids)},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _default_graph_factory(db_path: str):
    from mempalace.knowledge_graph import KnowledgeGraph

    return KnowledgeGraph(db_path=db_path)


def rebuild_kg_projection(
    dataset_dir: Path,
    plans: Iterable[Plan],
    *,
    graph_factory: Callable[[str], object] | None = None,
) -> dict[str, int | bool]:
    """Atomically replace only plan-owned KG triples.

    Plan lifecycle state remains structured data. The graph receives only stable plan
    nodes plus participant and location edges backed by the plan's initial sources.
    """
    db_path = dataset_dir / ".mempalace" / "palace" / "knowledge_graph.sqlite3"
    if not db_path.exists():
        return {"available": False, "plans": 0, "relationships": 0}

    ordered = sorted(plans, key=lambda item: item.id)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix="plan-kg-", suffix=".sqlite3", dir=db_path.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    graph = None
    relationships = 0
    try:
        source = sqlite3.connect(db_path)
        target = sqlite3.connect(temporary)
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()

        connection = sqlite3.connect(temporary)
        try:
            connection.execute("DELETE FROM triples WHERE adapter_name = ?", (PLAN_KG_ADAPTER,))
            connection.commit()
        finally:
            connection.close()

        factory = graph_factory or _default_graph_factory
        graph = factory(str(temporary))
        for plan in ordered:
            node = _node(plan)
            graph.add_entity(node, entity_type="plan", properties={
                "plan_id": plan.id, "title": plan.title, "source_ids": list(plan.source_ids),
            })
            provenance = _source(plan)
            for participant in plan.participants:
                graph.add_triple(
                    subject=node, predicate="plan_participant", obj=participant,
                    valid_from=plan.proposed_at.date().isoformat(), confidence=plan.confidence,
                    source_file=provenance, adapter_name=PLAN_KG_ADAPTER,
                )
                relationships += 1
            if plan.location:
                graph.add_triple(
                    subject=node, predicate="plan_location", obj=plan.location,
                    valid_from=plan.proposed_at.date().isoformat(), confidence=plan.confidence,
                    source_file=provenance, adapter_name=PLAN_KG_ADAPTER,
                )
                relationships += 1
        graph.close()
        graph = None
        os.replace(temporary, db_path)
        return {"available": True, "plans": len(ordered), "relationships": relationships}
    finally:
        if graph is not None:
            graph.close()
        temporary.unlink(missing_ok=True)
        Path(str(temporary) + "-wal").unlink(missing_ok=True)
        Path(str(temporary) + "-shm").unlink(missing_ok=True)
