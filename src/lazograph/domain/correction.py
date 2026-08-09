"""Immutable contracts for user-authoritative knowledge corrections."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


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
    fingerprint: str
    retract: Claim
    assert_claim: Claim
    matched_claims: tuple[Claim, ...]
    already_applied: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_text": self.raw_text,
            "dataset_slug": self.dataset_slug,
            "fingerprint": self.fingerprint,
            "retract": self.retract.to_dict(),
            "assert": self.assert_claim.to_dict(),
            "matched_claims": [claim.to_dict() for claim in self.matched_claims],
            "already_applied": self.already_applied,
        }
