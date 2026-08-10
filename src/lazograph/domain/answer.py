"""Grounded answer contracts shared across providers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class Evidence:
    message_id: str
    sender: str
    source_file: str
    timestamp: str | None
    excerpt: str
    score: float
    source_type: str = ""
    record_kind: str = ""
    authority: str = ""
    authored_by: str = ""
    confidence: float | None = None
    imported_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProviderOutput:
    text: str
    citation_ids: tuple[str, ...]
    confidence: float
    abstained: bool = False


@dataclass(frozen=True)
class Answer:
    text: str
    citations: tuple[Evidence, ...]
    confidence: float
    entities: tuple[str, ...]
    retrieval_summary: dict[str, Any] = field(default_factory=dict)
    abstained: bool = False
    facts: tuple[str, ...] = ()
    inferences: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "citations": [evidence.to_dict() for evidence in self.citations],
            "confidence": self.confidence,
            "entities": list(self.entities),
            "retrieval_summary": self.retrieval_summary,
            "abstained": self.abstained,
            "facts": list(self.facts),
            "inferences": list(self.inferences),
        }
