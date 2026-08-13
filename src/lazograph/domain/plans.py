"""Validated, deterministic contracts for derived personal plans."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from typing import Any, Iterable

PLAN_STATUSES = frozenset({"proposed", "pending", "scheduled", "completed", "cancelled"})
_ALLOWED_TRANSITIONS = {
    "proposed": {"pending", "scheduled", "cancelled"},
    "pending": {"scheduled", "completed", "cancelled"},
    "scheduled": {"pending", "completed", "cancelled"},
    "completed": set(),
    "cancelled": set(),
}


class PlanValidationError(ValueError):
    """A plan record cannot safely become a derived projection."""


def _source_ids(values: Iterable[str]) -> tuple[str, ...]:
    ids = tuple(sorted({str(value).strip() for value in values if str(value).strip()}))
    if not ids:
        raise PlanValidationError("Plan provenance requires at least one source ID.")
    return ids


def _when(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise PlanValidationError(f"{field} must be timezone-aware; host-local time is not allowed.")
    return value


def _confidence(value: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise PlanValidationError("Plan confidence must be between 0 and 1.") from exc
    if not 0 <= result <= 1:
        raise PlanValidationError("Plan confidence must be between 0 and 1.")
    return result


def plan_id(title: str, participants: Iterable[str], proposed_at: datetime, source_ids: Iterable[str]) -> str:
    """Return a stable ID from the initial, source-backed plan identity."""
    when = _when(proposed_at, "proposed_at").isoformat()
    members = sorted({str(value).casefold().strip() for value in participants if str(value).strip()})
    normalized_title = str(title).casefold().strip()
    if not normalized_title:
        raise PlanValidationError("Plan title cannot be empty.")
    value = "|".join((normalized_title, ",".join(members), when, ",".join(_source_ids(source_ids))))
    return "plan-" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class PlanTransition:
    from_status: str
    to_status: str
    occurred_at: datetime
    source_ids: tuple[str, ...]
    confidence: float
    provenance: str = "source"

    def __post_init__(self) -> None:
        if self.from_status not in PLAN_STATUSES or self.to_status not in PLAN_STATUSES:
            raise PlanValidationError("Plan transition has an unsupported status.")
        if self.to_status not in _ALLOWED_TRANSITIONS[self.from_status]:
            raise PlanValidationError(f"Invalid plan transition: {self.from_status} -> {self.to_status}.")
        object.__setattr__(self, "occurred_at", _when(self.occurred_at, "occurred_at"))
        object.__setattr__(self, "source_ids", _source_ids(self.source_ids))
        object.__setattr__(self, "confidence", _confidence(self.confidence))
        if not str(self.provenance).strip():
            raise PlanValidationError("Plan transition provenance cannot be empty.")

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["occurred_at"] = self.occurred_at.isoformat()
        result["source_ids"] = list(self.source_ids)
        return result

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "PlanTransition":
        try:
            return cls(
                from_status=value["from_status"], to_status=value["to_status"],
                occurred_at=datetime.fromisoformat(value["occurred_at"]),
                source_ids=tuple(value["source_ids"]), confidence=value["confidence"],
                provenance=value.get("provenance", "source"),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise PlanValidationError("Plan transition is invalid.") from exc


@dataclass(frozen=True)
class Plan:
    id: str
    title: str
    status: str
    participants: tuple[str, ...]
    proposed_at: datetime
    scheduled_for: datetime | None
    location: str | None
    source_ids: tuple[str, ...]
    confidence: float
    transitions: tuple[PlanTransition, ...] = ()

    def __post_init__(self) -> None:
        title = str(self.title).strip()
        participants = tuple(sorted({str(value).strip() for value in self.participants if str(value).strip()}, key=str.casefold))
        if not title or self.status not in PLAN_STATUSES:
            raise PlanValidationError("Plan requires a title and supported status.")
        object.__setattr__(self, "title", title)
        object.__setattr__(self, "participants", participants)
        object.__setattr__(self, "proposed_at", _when(self.proposed_at, "proposed_at"))
        if self.scheduled_for is not None:
            object.__setattr__(self, "scheduled_for", _when(self.scheduled_for, "scheduled_for"))
        object.__setattr__(self, "source_ids", _source_ids(self.source_ids))
        object.__setattr__(self, "confidence", _confidence(self.confidence))
        expected = plan_id(title, participants, self.proposed_at, self.source_ids)
        if self.id != expected:
            raise PlanValidationError("Plan ID does not match its initial identity.")
        current = "proposed"
        for transition in self.transitions:
            if transition.from_status != current:
                raise PlanValidationError("Plan transitions must form one ordered lifecycle.")
            current = transition.to_status
        if self.status != current:
            raise PlanValidationError("Plan status must match its latest transition.")

    @classmethod
    def create(cls, title: str, participants: Iterable[str], proposed_at: datetime, source_ids: Iterable[str], *, confidence: float, location: str | None = None) -> "Plan":
        sources = _source_ids(source_ids)
        return cls(plan_id(title, participants, proposed_at, sources), title, "proposed", tuple(participants), proposed_at, None, location, sources, confidence)

    def transition(self, to_status: str, occurred_at: datetime, source_ids: Iterable[str], *, confidence: float, provenance: str = "source", scheduled_for: datetime | None = None) -> "Plan":
        transition = PlanTransition(self.status, to_status, occurred_at, tuple(source_ids), confidence, provenance)
        return replace(self, status=to_status, scheduled_for=scheduled_for if scheduled_for is not None else self.scheduled_for, confidence=transition.confidence, transitions=(*self.transitions, transition))

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "title": self.title, "status": self.status, "participants": list(self.participants), "proposed_at": self.proposed_at.isoformat(), "scheduled_for": self.scheduled_for.isoformat() if self.scheduled_for else None, "location": self.location, "source_ids": list(self.source_ids), "confidence": self.confidence, "transitions": [item.to_dict() for item in self.transitions]}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Plan":
        try:
            return cls(value["id"], value["title"], value["status"], tuple(value.get("participants", ())), datetime.fromisoformat(value["proposed_at"]), datetime.fromisoformat(value["scheduled_for"]) if value.get("scheduled_for") else None, value.get("location"), tuple(value["source_ids"]), value["confidence"], tuple(PlanTransition.from_dict(item) for item in value.get("transitions", ())))
        except (KeyError, TypeError, ValueError) as exc:
            raise PlanValidationError("Plan record is invalid.") from exc
