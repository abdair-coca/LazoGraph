"""Immutable contracts for user-authoritative knowledge corrections."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


SYMMETRIC_RELATIONS = frozenset({
    "communicates_with",
    "cousin_of",
    "coworker_of",
    "friend_of",
    "romantic_partner",
    "sibling_of",
    "spouse_of",
})


def semantic_claim_id(subject: str, predicate: str, object_name: str) -> str:
    """Build a rebuild-stable ID from a canonical relationship tuple."""
    endpoints = [subject.casefold().strip(), object_name.casefold().strip()]
    if predicate in SYMMETRIC_RELATIONS:
        endpoints.sort()
    value = "|".join((endpoints[0], predicate.casefold().strip(), endpoints[1]))
    return "base-" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class Claim:
    subject: str
    predicate: str
    object: str
    confidence: float
    source: str
    claim_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CorrectionPreview:
    raw_text: str
    dataset_slug: str
    dataset_dir: Path
    fingerprint: str
    retract: Claim
    assert_claim: Claim
    matched_claims: tuple[Claim, ...]
    already_applied: bool = False
    pii_flags: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_text": self.raw_text,
            "dataset_slug": self.dataset_slug,
            "dataset_dir": str(self.dataset_dir),
            "fingerprint": self.fingerprint,
            "retract": self.retract.to_dict(),
            "assert": self.assert_claim.to_dict(),
            "matched_claims": [claim.to_dict() for claim in self.matched_claims],
            "already_applied": self.already_applied,
            "pii_flags": list(self.pii_flags),
        }
