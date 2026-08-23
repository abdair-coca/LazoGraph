"""Participant-isolated, source-backed personal suggestions."""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from lazograph.domain.answer import Answer, Evidence
from lazograph.domain.identity import IdentityResolutionError, load_profiles
from lazograph.features.ask_person.service import (
    MemorySearch,
    _semantic_score,
    _source_index,
    _terms,
    detect_language,
)
from lazograph.features.correct_knowledge.evidence import correction_evidence
from lazograph.features.pending_plans import PlanProjectionError, list_plans
from lazograph.features.pending_plans.service import _evidence as plan_evidence
from lazograph.features.ask_person.service import GroundingError
from lazograph.ports.llm import LLMProvider
from scripts import query_memory


class SuggestionQuestionError(IdentityResolutionError):
    """Suggestion target cannot be resolved to exactly one canonical participant."""


_SUGGESTION_QUESTION = re.compile(
    r"\b(?:gift|gifts|present|presents|give|buy|choose|recommend|suggest|regalo|regalos|"
    r"regalar|regalarle|obsequio|obsequios|recomendar|sugerir)\b",
    re.IGNORECASE,
)
_RELATIONSHIP_QUESTION = re.compile(
    r"\b(?:how|cómo)\b.{0,60}\b(?:relationship|relation|related|connected|relación|"
    r"relacionado|conectado|vínculo|vinculo)\b|"
    r"\b(?:relationship|relation|relación|vínculo|vinculo)\b.{0,40}\b(?:with|between|con|entre)\b",
    re.IGNORECASE,
)
_SENSITIVE = re.compile(
    r"\b(?:diagnos(?:is|e|ed)|depression|anxiety|trauma|abuse|addiction|therapy|"
    r"medical|medic(?:al|ina)|diagnóstico|depresión|ansiedad|trauma|abuso|adicción|"
    r"terapia|salud|password|contraseña|credit\s+card|tarjeta)\b"
    r"|\b[\w.+-]+@[\w-]+\.[\w.-]+\b",
    re.IGNORECASE,
)
_PREFERENCE = re.compile(
    r"\b(?:like|likes|love|loves|prefer|prefers|favorite|favourite|enjoy|enjoys|gusta|encanta|"
    r"prefiere|favorit[oa]|inter[eé]s|interest|hobby|pasatiempo)\b",
    re.IGNORECASE,
)
_POSITIVE = re.compile(
    r"\b(?:like|likes|love|loves|prefer|prefers|favorite|favourite|enjoy|enjoys|gusta|encanta|"
    r"prefiere|favorit[oa])\b",
    re.IGNORECASE,
)
_NEGATIVE = re.compile(
    r"\b(?:not|don't|doesn't|no|not?\s+like|no\s+me\s+gust)\b",
    re.IGNORECASE,
)
_CONCRETE_PREFERENCE = re.compile(
    r"\b(?:i\s+(?:like|love|prefer|enjoy)|me\s+(?:gust\w*|encant\w*)|"
    r"prefier\w*|mi\s+favorit[oa]\s+es|me\s+interes\w*)\s+"
    r"(?P<object>[a-záéíóúüñ0-9][^.!?]{2,})",
    re.IGNORECASE,
)


def _key(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", normalized).strip()


def is_suggestion_question(question: str) -> bool:
    """Recognize suggestion requests without deciding their participant target."""
    return bool(_SUGGESTION_QUESTION.search(question)) and not _RELATIONSHIP_QUESTION.search(question)


def _aliases(profile: dict) -> set[str]:
    values = {str(profile.get("name", "")).strip()}
    aliases = profile.get("aliases", [])
    if isinstance(aliases, list):
        values.update(str(alias).strip() for alias in aliases)
    canonical = _key(str(profile.get("name", ""))).split()
    if canonical and len(canonical[0]) >= 3:
        values.add(canonical[0])
    return {value for value in values if value}


def resolve_suggestion_participant(dataset_dir: Path, question: str) -> dict:
    """Resolve exactly one mentioned alias; never infer a default participant."""
    profiles = load_profiles(dataset_dir)
    owners: dict[str, set[str]] = defaultdict(set)
    by_name = {str(profile.get("name", "")).strip(): profile for profile in profiles}
    positions: dict[str, int] = {}
    normalized = _key(question)
    for profile in profiles:
        canonical = str(profile.get("name", "")).strip()
        for alias in _aliases(profile):
            alias_key = _key(alias)
            if alias_key:
                owners[alias_key].add(canonical)

    for alias_key in sorted(owners, key=len, reverse=True):
        match = re.search(rf"(?<!\w){re.escape(alias_key)}(?!\w)", normalized)
        if not match:
            continue
        matches = owners[alias_key]
        if len(matches) > 1:
            raise SuggestionQuestionError(
                f'Alias "{alias_key}" is ambiguous: {", ".join(sorted(matches))}'
            )
        canonical = next(iter(matches))
        positions[canonical] = min(positions.get(canonical, match.start()), match.start())

    if len(positions) != 1:
        if not positions:
            raise SuggestionQuestionError(
                "Suggestion questions must mention exactly one participant."
            )
        raise SuggestionQuestionError(
            "Suggestion question is ambiguous; mention exactly one participant: "
            + ", ".join(sorted(positions))
        )
    return by_name[next(iter(positions))]


def _evidence_from_results(
    dataset_dir: Path,
    participant: str,
    question: str,
    raw_results: Sequence[dict],
    *,
    limit: int,
) -> tuple[list[Evidence], dict[str, int]]:
    by_vector_id, by_fallback = _source_index(dataset_dir, participant)
    question_terms = _terms(question) - {"gift", "gifts", "present", "regalo", "regalos"}
    ranked: list[tuple[float, int, Evidence]] = []
    rejected_sender = 0
    rejected_unpersisted = 0
    for result in raw_results:
        metadata = result.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
        sender = str(metadata.get("sender", "")).strip()
        if sender.casefold() != participant.casefold():
            rejected_sender += 1
            continue
        record = by_vector_id.get(str(result.get("id", "")))
        if record is None:
            record = by_fallback.get((result.get("content"), sender.casefold(), metadata.get("authored_at")))
        if record is None:
            rejected_unpersisted += 1
            continue
        message = record["message"]
        excerpt = re.sub(r"\s+", " ", str(message.get("content", ""))).strip()[:500]
        if not excerpt:
            continue
        content_terms = _terms(excerpt)
        lexical = sum(term in content_terms for term in question_terms)
        source_type = str(message.get("source_type", ""))
        preference = bool(_PREFERENCE.search(excerpt))
        score = _semantic_score(result.get("distance")) + (0.1 if preference else 0.0)
        score += 0.05 if source_type == "user_context" else 0.0
        evidence = Evidence(
            message_id=record["message_id"],
            sender=sender,
            source_file=record["source_file"],
            timestamp=message.get("timestamp"),
            excerpt=excerpt,
            score=round(min(1.0, score), 4),
            source_type=source_type,
            record_kind=str(message.get("metadata", {}).get("record_kind", "")),
            authority=str(message.get("metadata", {}).get("authority", "")),
            authored_by=str(message.get("metadata", {}).get("authored_by", "")),
            confidence=(
                float(message.get("metadata", {}).get("confidence"))
                if isinstance(message.get("metadata", {}).get("confidence"), (int, float))
                else None
            ),
            imported_at=str(message.get("metadata", {}).get("imported_at", "")),
        )
        ranked.append((score, lexical + (1 if preference else 0), evidence))
    ranked.sort(key=lambda item: (-item[0], -item[1], item[2].message_id))
    return [item[2] for item in ranked[:limit]], {
        "raw_results": len(raw_results),
        "verified_results": len(ranked),
        "rejected_sender": rejected_sender,
        "rejected_unpersisted": rejected_unpersisted,
    }


def _active_plan_evidence(dataset_dir: Path, participant: str, limit: int) -> tuple[list[Evidence], list[dict]]:
    try:
        available_plans = list_plans(dataset_dir)
    except PlanProjectionError:
        if not (dataset_dir / "plans" / "projection.json").exists():
            return [], []
        raise
    plans = [
        plan for plan in available_plans
        if plan.status in {"proposed", "pending", "scheduled"}
        and participant.casefold() in {item.casefold() for item in plan.participants}
    ]
    result: list[Evidence] = []
    summaries = []
    for plan in plans:
        source_ids = [plan.source_ids[0]]
        if plan.transitions:
            source_ids.append(plan.transitions[-1].source_ids[-1])
        for source_id in source_ids:
            if len(result) >= limit:
                break
            item = plan_evidence(dataset_dir, source_id, plan.confidence)
            schedule = plan.scheduled_for.isoformat() if plan.scheduled_for else "unscheduled"
            details = (
                f"Active plan: {plan.title}; status={plan.status}; scheduled_for={schedule}; "
                f"location={plan.location or 'unknown'}. Source: {item.excerpt}"
            )
            item = replace(item, excerpt=details[:500])
            if not any(existing.message_id == item.message_id for existing in result):
                result.append(item)
        summaries.append({
            "title": plan.title,
            "status": plan.status,
            "scheduled_for": plan.scheduled_for.isoformat() if plan.scheduled_for else None,
            "location": plan.location,
        })
    return result, summaries


def _conflicting_preferences(evidence: Sequence[Evidence]) -> bool:
    ordinary = [item for item in evidence if item.source_type != "user_correction"]
    positive = [item for item in ordinary if _POSITIVE.search(item.excerpt)]
    negative = [item for item in ordinary if _NEGATIVE.search(item.excerpt)]
    for left in positive:
        for right in negative:
            if _terms(left.excerpt) & _terms(right.excerpt):
                return True
    return False


def _has_concrete_preference(value: str) -> bool:
    match = _CONCRETE_PREFERENCE.search(value)
    if not match:
        return False
    words = _terms(match.group("object"))
    return bool(words - {"que", "eso", "esto", "algo"})


def _abstention(
    participant: str | None,
    language: str,
    summary: dict[str, Any],
    *,
    reason: str,
    missing: Sequence[str] = (),
) -> Answer:
    name = participant or "that participant"
    text = (
        f"No encontré contexto suficiente para sugerir algo para {name}."
        if language == "es"
        else f"I found insufficient context to suggest something for {name}."
    )
    return Answer(
        text=text,
        citations=(),
        confidence=0.0,
        entities=(participant,) if participant else (),
        retrieval_summary={**summary, "abstention_reason": reason},
        abstained=True,
        missing_information=tuple(missing),
    )


def _validate_suggestion_output(output, evidence: Sequence[Evidence]) -> tuple[Evidence, ...]:
    available = {item.message_id: item for item in evidence}
    if output.abstained:
        return ()
    if not output.suggestions:
        raise GroundingError("Suggestion provider returned no structured suggestions.")
    invalid = [item for item in output.citation_ids if item not in available]
    if invalid:
        raise GroundingError(f"Suggestion provider cited unavailable evidence: {', '.join(invalid)}")
    if not output.citation_ids:
        raise GroundingError("Suggestion provider returned no citations.")
    for citation in output.citation_ids:
        if f"[{citation}]" not in output.text:
            raise GroundingError(f"Suggestion provider omitted citation marker: {citation}")
    for suggestion in output.suggestions:
        if not any(f"[{citation}]" in suggestion for citation in output.citation_ids):
            raise GroundingError("Suggestion omitted evidence citation marker.")
    return tuple(available[item] for item in dict.fromkeys(output.citation_ids))


def _section(text: str, heading: str) -> tuple[str, ...]:
    lines = text.splitlines()
    try:
        start = next(index for index, line in enumerate(lines) if line.strip() == heading) + 1
    except StopIteration:
        return ()
    end = next(
        (index for index in range(start, len(lines)) if lines[index].strip().endswith(":")),
        len(lines),
    )
    return tuple(line.strip()[2:] if line.strip().startswith("- ") else line.strip() for line in lines[start:end] if line.strip())


def answer_suggestion_question(
    dataset_dir: Path,
    question: str,
    provider: LLMProvider,
    *,
    limit: int = 5,
    evidence_budget: int = 2500,
    memory_search: MemorySearch = query_memory.search_memory,
) -> Answer:
    """Generate a read-only suggestion from selected participant evidence."""
    language = detect_language(question)
    summary: dict[str, Any] = {"answer_mode": "suggestions", "provider": provider.name, "hosted": provider.hosted}
    try:
        profile = resolve_suggestion_participant(dataset_dir, question)
    except SuggestionQuestionError as exc:
        return _abstention(None, language, summary, reason="unresolved_target", missing=(str(exc),))
    participant = str(profile.get("name", "")).strip()
    try:
        raw_results = memory_search(
            dataset_dir,
            question + " preferences interests likes dislikes constraints",
            participant=participant,
            limit=min(max(limit * 6, 20), 100),
        )
        semantic, search_summary = _evidence_from_results(
            dataset_dir, participant, question, raw_results, limit=limit
        )
        corrections = correction_evidence(dataset_dir, participant, set(), limit=limit)
        plans, active_plans = _active_plan_evidence(dataset_dir, participant, limit=max(1, limit // 2))
    except (PlanProjectionError, OSError, RuntimeError, ValueError) as exc:
        return _abstention(
            participant,
            language,
            summary,
            reason="evidence_unavailable",
            missing=(str(exc),),
        )

    combined: list[Evidence] = []
    ordered_evidence = [
        *corrections[:1],
        *plans[:2],
        *semantic,
        *corrections[1:],
        *plans[2:],
    ]
    for item in ordered_evidence:
        if any(existing.message_id == item.message_id for existing in combined):
            continue
        cost = len(item.excerpt)
        if combined and sum(len(existing.excerpt) for existing in combined) + cost > evidence_budget:
            continue
        combined.append(item)
        if len(combined) >= limit:
            break
    consumed = sum(len(item.excerpt) for item in combined)
    summary.update({
        **search_summary,
        "participant_filter": participant,
        "semantic_results": len(semantic),
        "correction_results": len(corrections),
        "plan_results": len(plans),
        "active_plans": active_plans,
        "selected_results": len(combined),
        "evidence_chars": consumed,
    })
    if any(_SENSITIVE.search(item.excerpt) for item in combined):
        return _abstention(
            participant,
            language,
            summary,
            reason="sensitive_context",
            missing=("non-sensitive preference or occasion context",),
        )
    if _conflicting_preferences(combined):
        return _abstention(
            participant,
            language,
            summary,
            reason="conflicting_preference_evidence",
            missing=("a confirmed current preference",),
        )
    useful = [
        item for item in combined
        if _has_concrete_preference(item.excerpt) or item.source_type == "user_context"
    ]
    if not useful:
        return _abstention(
            participant,
            language,
            summary,
            reason="insufficient_relevant_evidence",
            missing=("a stated preference or interest",),
        )

    context = {
        "answer_mode": "suggestions",
        "entities": [participant],
        "active_plans": active_plans,
    }
    output = provider.generate(question, participant, combined, context, language=language)
    if output.abstained:
        return _abstention(
            participant,
            language,
            summary,
            reason="provider_abstained",
            missing=output.missing_information,
        )
    citations = _validate_suggestion_output(output, combined)
    heading = "Inferencia" if language == "es" else "Inference"
    inferences = _section(output.text, heading + ":")
    facts = tuple(f"{item.excerpt} [{item.message_id}]" for item in citations)
    return Answer(
        text=output.text,
        citations=citations,
        confidence=max(0.0, min(1.0, output.confidence)),
        entities=(participant,),
        retrieval_summary=summary,
        facts=facts,
        inferences=inferences,
        suggestions=output.suggestions,
        missing_information=output.missing_information,
    )
