"""Participant-isolated retrieval, enrichment, generation, and validation."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from lazograph.domain.answer import Answer, Evidence
from lazograph.domain.identity import load_profiles, resolve_participant
from lazograph.ports.llm import LLMProvider
from scripts import ingest, query_kg, query_memory


class GroundingError(RuntimeError):
    """An answer failed evidence or citation validation."""


MemorySearch = Callable[..., list[dict]]
WORD_PATTERN = re.compile(r"[a-záéíóúüñ]+", re.IGNORECASE)
SPANISH_MARKERS = {
    "qué", "cuál", "cuáles", "cómo", "dónde", "cuando", "cuándo", "quién",
    "le", "sus", "sobre", "gusta", "gustan", "prefiere", "favorito", "favorita",
}
STOP_WORDS = {
    "a", "about", "al", "and", "are", "como", "con", "cosas", "cuál", "cuáles",
    "de", "del", "does", "el", "ella", "en", "es", "esta", "este", "for", "hacer",
    "he", "her", "him", "is", "la", "las", "le", "les", "lo", "los", "me", "mi",
    "my", "of", "para", "por", "que", "qué", "se", "she", "sobre", "su", "sus", "tiene",
    "tener",
    "the", "to", "un", "una", "what", "who", "y",
}
PREFERENCE_WORDS = {
    "gusta", "gustan", "gustar", "encanta", "encantan", "prefiere", "preferir",
    "favorito", "favorita", "like", "likes", "love", "loves", "prefer", "favorite",
}
PREFERENCE_EVIDENCE = re.compile(
    r"\b(?:me\s+gust\w*|me\s+encant\w*|amo\b|adoro\b|prefier\w*|"
    r"mi\s+favorit[oa]|i\s+like\b|i\s+love\b|my\s+favou?rite)\b",
    re.IGNORECASE,
)
RELATIONSHIP_WORDS = {
    "relationship", "relation", "related", "connected", "relación", "relacionado",
    "conectado", "vínculo", "vinculo",
}
NEGATIVE_PREFERENCE = re.compile(
    r"\b(?:no\s+me\s+gust\w*|no\s+me\s+encant\w*|i\s+(?:do\s+not|don't)\s+like)\b",
    re.IGNORECASE,
)


def detect_language(question: str) -> str:
    words = {word.casefold() for word in WORD_PATTERN.findall(question)}
    return "es" if "¿" in question or words & SPANISH_MARKERS else "en"


def resolve_question_participant(dataset_dir: Path, question: str) -> dict | None:
    """Resolve one participant explicitly named in a non-relationship question."""
    normalized = question.casefold()
    words = {word.casefold() for word in WORD_PATTERN.findall(question)}
    if words & RELATIONSHIP_WORDS:
        return None
    matches: dict[str, dict] = {}
    for profile in load_profiles(dataset_dir):
        canonical = str(profile.get("name", "")).strip()
        aliases = profile.get("aliases", [])
        names = [canonical, *(aliases if isinstance(aliases, list) else [])]
        for alias in names:
            value = str(alias).strip()
            if value and re.search(rf"(?<!\w){re.escape(value.casefold())}(?!\w)", normalized):
                matches[canonical] = profile
                break
    if len(matches) > 1:
        return None
    return next(iter(matches.values()), None)


def _terms(text: str) -> set[str]:
    return {
        word.casefold()
        for word in WORD_PATTERN.findall(text)
        if len(word) > 2 and word.casefold() not in STOP_WORDS
    }


def _topic_terms(question: str, participant: str) -> set[str]:
    terms = _terms(question) - _terms(participant)
    return terms - PREFERENCE_WORDS


def _semantic_score(distance: Any) -> float:
    if not isinstance(distance, (int, float)):
        return 0.0
    return max(0.0, min(1.0, 1.0 - float(distance)))


def _lexical_overlap(question_terms: set[str], content_terms: set[str]) -> int:
    """Match exact words plus conservative five-character inflection stems."""
    matches = 0
    for question_term in question_terms:
        if question_term in content_terms:
            matches += 1
            continue
        if len(question_term) < 5:
            continue
        prefix = question_term[:5]
        if any(len(content_term) >= 5 and content_term.startswith(prefix) for content_term in content_terms):
            matches += 1
    return matches


def _source_index(dataset_dir: Path, participant: str | None) -> tuple[dict[str, dict], dict[tuple, dict]]:
    by_vector_id: dict[str, dict] = {}
    by_fallback: dict[tuple, dict] = {}
    for source_path in sorted(dataset_dir.joinpath("sources").glob("*.jsonl")):
        with source_path.open(encoding="utf-8") as source:
            for line_number, line in enumerate(source, 1):
                try:
                    message = json.loads(line)
                except (json.JSONDecodeError, TypeError):
                    continue
                sender = str(message.get("metadata", {}).get("sender", "")).strip()
                if participant and sender.casefold() != participant.casefold():
                    continue
                record = {
                    "message": message,
                    "message_id": f"{source_path.name}:{line_number}",
                    "source_file": source_path.name,
                }
                try:
                    by_vector_id[ingest._vector_id(dataset_dir.name, message)] = record
                except (KeyError, TypeError):
                    pass
                fallback = (
                    message.get("content"),
                    sender.casefold(),
                    message.get("timestamp"),
                )
                by_fallback[fallback] = record
    return by_vector_id, by_fallback


def retrieve_evidence(
    dataset_dir: Path,
    question: str,
    participant: str | None,
    *,
    limit: int = 5,
    evidence_budget: int = 2500,
    memory_search: MemorySearch = query_memory.search_memory,
) -> tuple[list[Evidence], dict[str, Any]]:
    """Retrieve with sender filter, then verify every hit against persisted source lines."""
    candidate_limit = min(max(limit * 6, 20), 100)
    raw_results = memory_search(
        dataset_dir,
        question,
        participant=participant,
        limit=candidate_limit,
    )
    by_vector_id, by_fallback = _source_index(dataset_dir, participant)
    question_terms = _topic_terms(question, participant or "")
    question_words = {word.casefold() for word in WORD_PATTERN.findall(question)}
    preference_intent = bool(question_words & PREFERENCE_WORDS)
    ranked = []
    rejected_sender = 0
    rejected_unpersisted = 0

    for result in raw_results:
        metadata = result.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
        sender = str(metadata.get("sender", "")).strip()
        if participant and sender.casefold() != participant.casefold():
            rejected_sender += 1
            continue
        record = by_vector_id.get(str(result.get("id", "")))
        if record is None:
            fallback = (
                result.get("content"),
                sender.casefold(),
                metadata.get("authored_at"),
            )
            record = by_fallback.get(fallback)
        if record is None:
            rejected_unpersisted += 1
            continue

        message = record["message"]
        content = str(message.get("content", "")).strip()
        content_terms = _terms(content)
        lexical_overlap = _lexical_overlap(question_terms, content_terms)
        lexical_score = (
            lexical_overlap / len(question_terms) if question_terms else 0.0
        )
        semantic_score = _semantic_score(result.get("distance"))
        score = semantic_score * 0.8 + lexical_score * 0.2
        excerpt = re.sub(r"\s+", " ", content)[:min(500, evidence_budget)].strip()
        if not excerpt:
            continue
        ranked.append((
            score,
            lexical_overlap,
            bool(PREFERENCE_EVIDENCE.search(content)),
            Evidence(
                message_id=record["message_id"],
                sender=sender,
                source_file=record["source_file"],
                timestamp=message.get("timestamp"),
                excerpt=excerpt,
                score=round(score, 4),
                source_type=str(message.get("source_type", "")),
                record_kind=str(message.get("metadata", {}).get("record_kind", "")),
                authority=str(message.get("metadata", {}).get("authority", "")),
                authored_by=str(message.get("metadata", {}).get("authored_by", "")),
                confidence=(
                    float(message.get("metadata", {}).get("confidence"))
                    if isinstance(message.get("metadata", {}).get("confidence"), (int, float))
                    else None
                ),
                imported_at=str(message.get("metadata", {}).get("imported_at", "")),
            ),
        ))

    ranked.sort(key=lambda item: (-item[0], -item[1], item[3].message_id))
    eligible = [
        item for item in ranked
        if (not question_terms or item[1] > 0 or participant is None)
        and (not preference_intent or item[2])
    ]
    selected: list[Evidence] = []
    consumed = 0
    for _score, _overlap, _preference, evidence in eligible:
        cost = len(evidence.excerpt)
        if selected and consumed + cost > evidence_budget:
            continue
        selected.append(evidence)
        consumed += cost
        if len(selected) >= limit:
            break

    summary = {
        "participant_filter": participant,
        "raw_results": len(raw_results),
        "verified_results": len(ranked),
        "relevant_results": len(eligible),
        "selected_results": len(selected),
        "rejected_sender": rejected_sender,
        "rejected_unpersisted": rejected_unpersisted,
        "evidence_chars": consumed,
        "topic_terms": sorted(question_terms),
    }
    return selected, summary


def _question_supported(question: str, participant: str, evidence: Sequence[Evidence]) -> bool:
    if not evidence or max(item.score for item in evidence) < 0.42:
        return False
    words = {word.casefold() for word in WORD_PATTERN.findall(question)}
    topic_terms = _topic_terms(question, participant)
    if topic_terms:
        combined = set().union(*(_terms(item.excerpt) for item in evidence))
        if _lexical_overlap(topic_terms, combined) == 0:
            return False
    if words & PREFERENCE_WORDS:
        return any(PREFERENCE_EVIDENCE.search(item.excerpt) for item in evidence)
    return True


def _contradictory_preferences(
    question: str,
    participant: str,
    evidence: Sequence[Evidence],
) -> bool:
    topic_terms = _topic_terms(question, participant)
    words = {word.casefold() for word in WORD_PATTERN.findall(question)}
    if not topic_terms or not words & PREFERENCE_WORDS:
        return False
    positive = False
    negative = False
    for item in evidence:
        content_terms = _terms(item.excerpt)
        if _lexical_overlap(topic_terms, content_terms) == 0:
            continue
        if NEGATIVE_PREFERENCE.search(item.excerpt):
            negative = True
        elif PREFERENCE_EVIDENCE.search(item.excerpt):
            positive = True
    return positive and negative


def _enrichment(dataset_dir: Path, profile: dict) -> dict[str, Any]:
    participant = str(profile.get("name", ""))
    relationship_types: list[str] = []
    graph_exists = (
        dataset_dir.joinpath(".mempalace", "palace", "knowledge_graph.sqlite3").exists()
        or dataset_dir.joinpath(".mempalace", "kg-pending.json").exists()
    )
    try:
        if not graph_exists:
            raise FileNotFoundError
        _entities, relationships, _stats = query_kg._load_kg(
            dataset_dir,
            profiles=[profile],
        )
        relationship_types = sorted({
            str(rel.get("type", ""))
            for rel in relationships
            if participant in {rel.get("from"), rel.get("to")} and rel.get("type")
        })
    except (RuntimeError, OSError):
        relationship_types = []

    wiki_pages = []
    if profile.get("identity_type") == "persona":
        wiki_pages = sorted(
            path.stem
            for path in dataset_dir.joinpath("wiki").glob("*.md")
            if not path.name.startswith("_")
        )
    return {
        "identity_type": profile.get("identity_type", "unknown"),
        "message_count": profile.get("message_count", 0),
        "first_seen": profile.get("first_seen"),
        "last_seen": profile.get("last_seen"),
        "relationship_types": relationship_types,
        "wiki_pages": wiki_pages,
    }


def _abstention(
    participant: str,
    language: str,
    summary: dict[str, Any],
    *,
    reason: str,
) -> Answer:
    text = (
        f"No encontré evidencia suficiente para responder sobre {participant}."
        if language == "es"
        else f"I found insufficient evidence to answer about {participant}."
    )
    return Answer(
        text=text,
        citations=(),
        confidence=0.0,
        entities=(participant,),
        retrieval_summary={**summary, "abstention_reason": reason},
        abstained=True,
    )


def _validate_output(output, evidence: Sequence[Evidence]) -> tuple[Evidence, ...]:
    available = {item.message_id: item for item in evidence}
    if output.abstained:
        return ()
    if not output.citation_ids:
        raise GroundingError("Provider answer has no citations.")
    invalid = [citation for citation in output.citation_ids if citation not in available]
    if invalid:
        raise GroundingError(f"Provider cited unavailable evidence: {', '.join(invalid)}")
    missing_markers = [
        citation for citation in output.citation_ids
        if f"[{citation}]" not in output.text
    ]
    if missing_markers:
        raise GroundingError(
            f"Provider omitted citation markers: {', '.join(missing_markers)}"
        )
    return tuple(available[citation] for citation in dict.fromkeys(output.citation_ids))


def answer_about_person(
    dataset_dir: Path,
    question: str,
    about: str,
    provider: LLMProvider,
    *,
    limit: int = 5,
    evidence_budget: int = 2500,
    memory_search: MemorySearch = query_memory.search_memory,
) -> Answer:
    profile = resolve_participant(dataset_dir, about)
    participant = str(profile.get("name", "")).strip()
    language = detect_language(question)
    evidence, summary = retrieve_evidence(
        dataset_dir,
        question,
        participant,
        limit=limit,
        evidence_budget=evidence_budget,
        memory_search=memory_search,
    )
    from lazograph.features.correct_knowledge.evidence import correction_evidence

    correction_items = correction_evidence(
        dataset_dir,
        participant,
        _topic_terms(question, participant),
        limit=limit,
    )
    combined = []
    consumed = 0
    for item in [*correction_items, *evidence]:
        if any(existing.message_id == item.message_id for existing in combined):
            continue
        cost = len(item.excerpt)
        if combined and consumed + cost > evidence_budget:
            continue
        combined.append(item)
        consumed += cost
        if len(combined) >= limit:
            break
    evidence = combined
    summary = {
        **summary,
        "correction_results": len(correction_items),
        "selected_results": len(evidence),
        "evidence_chars": consumed,
    }
    summary = {**summary, "provider": provider.name, "hosted": provider.hosted}
    if _contradictory_preferences(question, participant, evidence):
        return _abstention(
            participant,
            language,
            summary,
            reason="contradictory_evidence",
        )
    if not _question_supported(question, participant, evidence):
        return _abstention(
            participant,
            language,
            summary,
            reason="insufficient_relevant_evidence",
        )

    context = _enrichment(dataset_dir, profile)
    output = provider.generate(
        question,
        participant,
        evidence,
        context,
        language=language,
    )
    if output.abstained:
        return _abstention(
            participant,
            language,
            summary,
            reason="provider_abstained",
        )
    citations = _validate_output(output, evidence)
    return Answer(
        text=output.text,
        citations=citations,
        confidence=max(0.0, min(1.0, output.confidence)),
        entities=(participant,),
        retrieval_summary={
            **summary,
            "kg_relationship_types": len(context["relationship_types"]),
            "wiki_pages": len(context["wiki_pages"]),
        },
    )


def answer_about_dataset(
    dataset_dir: Path,
    question: str,
    provider: LLMProvider,
    *,
    limit: int = 5,
    evidence_budget: int = 2500,
    memory_search: MemorySearch = query_memory.search_memory,
) -> Answer:
    """Answer questions that do not target one participant or one feature slice."""
    language = detect_language(question)
    evidence, summary = retrieve_evidence(
        dataset_dir,
        question,
        None,
        limit=limit,
        evidence_budget=evidence_budget,
        memory_search=memory_search,
    )
    summary = {
        **summary,
        "provider": provider.name,
        "hosted": provider.hosted,
        "answer_mode": "general",
    }
    if not evidence or max(item.score for item in evidence) < 0.42:
        text = (
            "No encontré evidencia suficiente en la conversación."
            if language == "es"
            else "I found insufficient evidence in the conversation."
        )
        return Answer(text, (), 0.0, (), {**summary, "abstention_reason": "insufficient_relevant_evidence"}, abstained=True)

    subject = "la conversación" if language == "es" else "the conversation"
    output = provider.generate(
        question,
        subject,
        evidence,
        {"answer_mode": "general"},
        language=language,
    )
    if output.abstained:
        return Answer(
            output.text,
            (),
            0.0,
            (),
            {**summary, "abstention_reason": "provider_abstained"},
            abstained=True,
        )
    citations = _validate_output(output, evidence)
    entities = tuple(dict.fromkeys(item.sender for item in citations if item.sender))
    return Answer(
        output.text,
        citations,
        max(0.0, min(1.0, output.confidence)),
        entities,
        {**summary, "selected_results": len(citations)},
    )
