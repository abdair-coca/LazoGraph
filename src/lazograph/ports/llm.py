"""Provider-neutral answer generation boundary."""

from __future__ import annotations

from typing import Any, Protocol, Sequence, runtime_checkable

from lazograph.domain.answer import Evidence, ProviderOutput


@runtime_checkable
class LLMProvider(Protocol):
    name: str
    hosted: bool

    def generate(
        self,
        question: str,
        participant: str,
        evidence: Sequence[Evidence],
        context: dict[str, Any],
        *,
        language: str,
    ) -> ProviderOutput:
        """Generate only from selected evidence and minimal safe context."""
