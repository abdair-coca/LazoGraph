"""Read-only product queries over the source-derived plan projection."""

from __future__ import annotations

import json
import re
from pathlib import Path

from lazograph.domain.answer import Answer, Evidence
from lazograph.domain.plans import PLAN_STATUSES, Plan

from .storage import PlanProjectionError, load_projection


_PLAN_QUESTION = re.compile(
    r"\b(?:pending|upcoming|current|pendiente(?:s)?|pr[oó]xim[oa]s?|actuales?)\b.*"
    r"\b(?:plans?|commitments?|activities|planes?|compromisos?|actividades?)\b|"
    r"\b(?:plans?|commitments?|activities|planes?|compromisos?|actividades?)\b.*"
    r"\b(?:pending|upcoming|current|pendiente(?:s)?|pr[oó]xim[oa]s?|actuales?)\b",
    re.IGNORECASE,
)


def is_plan_question(question: str) -> bool:
    """Recognize only explicit current/pending plan questions."""
    return bool(_PLAN_QUESTION.search(question))


def list_plans(
    dataset_dir: Path,
    *,
    status: str | None = None,
    participant: str | None = None,
) -> list[Plan]:
    if status is not None and status not in PLAN_STATUSES:
        raise PlanProjectionError(f"Unsupported plan status: {status}")
    participant_key = participant.casefold().strip() if participant else None
    return [
        plan for plan in load_projection(dataset_dir)
        if (status is None or plan.status == status)
        and (
            participant_key is None
            or participant_key in {value.casefold() for value in plan.participants}
        )
    ]


def show_plan(dataset_dir: Path, plan_id: str) -> Plan:
    for plan in load_projection(dataset_dir):
        if plan.id == plan_id:
            return plan
    raise PlanProjectionError(f"Plan not found: {plan_id}")


def _evidence(dataset_dir: Path, source_id: str, confidence: float) -> Evidence:
    try:
        filename, line = source_id.rsplit(":", 1)
        message = json.loads(
            dataset_dir.joinpath("sources", filename)
            .read_text(encoding="utf-8").splitlines()[int(line) - 1]
        )
        metadata = message.get("metadata", {})
        return Evidence(
            source_id,
            str(metadata.get("sender", "unknown")),
            filename,
            message.get("timestamp"),
            str(message.get("content", "")),
            confidence,
            source_type="plan_source",
            record_kind="plan_transition",
            confidence=confidence,
        )
    except (OSError, ValueError, IndexError, json.JSONDecodeError) as exc:
        raise PlanProjectionError(f"Plan evidence is missing: {source_id}") from exc


def answer_plan_question(dataset_dir: Path, question: str) -> Answer:
    """Answer from active plan states and cite creation/latest-transition sources."""
    plans = list_plans(dataset_dir)
    active = [plan for plan in plans if plan.status in {"proposed", "pending", "scheduled"}]
    spanish = bool(re.search(r"[¿áéíóú]|\b(?:tenemos|planes|pendiente)\b", question, re.I))
    if not active:
        text = "No encontré planes pendientes respaldados por fuentes." if spanish else \
            "I found no source-backed pending plans."
        return Answer(text, (), 1.0, (), {"plan_count": 0}, facts=(text,))
    citations: dict[str, Evidence] = {}
    facts = []
    for plan in active:
        source_ids = [plan.source_ids[0]]
        if plan.transitions:
            source_ids.append(plan.transitions[-1].source_ids[-1])
        for source_id in source_ids:
            citations[source_id] = _evidence(dataset_dir, source_id, plan.confidence)
        date = plan.scheduled_for.isoformat() if plan.scheduled_for else "unscheduled"
        facts.append(
            f"{plan.title} ({plan.status}; {date}) "
            + " ".join(f"[{source_id}]" for source_id in source_ids)
        )
    heading = "Planes pendientes:" if spanish else "Pending plans:"
    return Answer(
        heading + "\n" + "\n".join(f"- {fact}" for fact in facts),
        tuple(citations.values()),
        min(plan.confidence for plan in active),
        tuple(sorted({person for plan in active for person in plan.participants}, key=str.casefold)),
        {"plan_count": len(active), "statuses": sorted({plan.status for plan in active})},
        facts=tuple(facts),
    )
