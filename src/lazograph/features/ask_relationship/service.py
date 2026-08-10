"""Effective-graph relationship answers with source-backed facts and explicit inference."""

from __future__ import annotations

import json
import re
import unicodedata
from collections import defaultdict, deque
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from lazograph.domain.answer import Answer, Evidence
from lazograph.domain.correction import semantic_claim_id
from lazograph.domain.identity import IdentityResolutionError, load_profiles
from lazograph.features.ask_person.service import (
    MemorySearch,
    _validate_output,
    detect_language,
    retrieve_evidence,
)
from lazograph.features.correct_knowledge.evidence import correction_evidence
from lazograph.ports.llm import LLMProvider
from scripts import query_kg, query_memory


class RelationshipQuestionError(IdentityResolutionError):
    """A relationship question does not identify exactly two safe participants."""


GraphLoader = Callable[..., tuple[set[str], list[dict], dict | None]]

RELATION_LABELS = {
    "communicates_with": {"en": "communicates with", "es": "se comunica con"},
    "romantic_partner": {"en": "is a romantic partner of", "es": "es pareja de"},
    "friend_of": {"en": "is a friend of", "es": "es amigo/a de"},
    "sibling_of": {"en": "is a sibling of", "es": "es hermano/a de"},
    "cousin_of": {"en": "is a cousin of", "es": "es primo/a de"},
    "coworker_of": {"en": "is a coworker of", "es": "es colega de"},
    "spouse_of": {"en": "is a spouse of", "es": "es cónyuge de"},
    "parent_of": {"en": "is a parent of", "es": "es padre/madre de"},
    "child_of": {"en": "is a child of", "es": "es hijo/a de"},
    "manager_of": {"en": "manages", "es": "dirige a"},
    "partner_of": {"en": "is a partner of", "es": "es pareja de"},
    "reports_to": {"en": "reports to", "es": "reporta a"},
    "colleague_of": {"en": "is a colleague of", "es": "es colega de"},
}

RELATION_SEARCH_TERMS = {
    "communicates_with": "conversation chat message communicate habla mensaje conversación",
    "romantic_partner": "romantic partner girlfriend boyfriend pareja novia novio amor",
    "friend_of": "friend friendship amigo amiga amistad",
    "sibling_of": "sibling brother sister hermano hermana",
    "cousin_of": "cousin primo prima",
    "coworker_of": "coworker colleague trabajo colega",
    "spouse_of": "spouse husband wife esposo esposa cónyuge",
    "parent_of": "parent father mother padre madre",
    "child_of": "child son daughter hijo hija",
    "manager_of": "manager boss jefe jefa",
    "partner_of": "partner pareja",
    "reports_to": "manager boss jefe jefa",
    "colleague_of": "coworker colleague colega",
}

FIRST_PERSON = re.compile(r"\b(?:yo|mi|mio|mia|conmigo|tengo|i|me|my|mine)\b")


def _key(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", normalized).strip()


def _aliases(profile: dict) -> set[str]:
    aliases = {str(profile.get("name", "")).strip()}
    raw = profile.get("aliases", [])
    if isinstance(raw, list):
        aliases.update(str(item).strip() for item in raw)
    return {item for item in aliases if item}


def resolve_relationship_participants(dataset_dir: Path, question: str) -> tuple[dict, dict]:
    """Resolve two canonical participants from aliases, with optional first-person focal identity."""
    profiles = load_profiles(dataset_dir)
    normalized_question = _key(question)
    alias_owners: dict[str, set[str]] = defaultdict(set)
    by_name = {str(profile.get("name", "")).strip(): profile for profile in profiles}
    positions: dict[str, int] = {}

    for profile in profiles:
        canonical = str(profile.get("name", "")).strip()
        for alias in _aliases(profile):
            alias_key = _key(alias)
            if alias_key:
                alias_owners[alias_key].add(canonical)
        canonical_tokens = _key(canonical).split()
        if canonical_tokens and len(canonical_tokens[0]) >= 3:
            alias_owners[canonical_tokens[0]].add(canonical)

    for alias_key in sorted(alias_owners, key=len, reverse=True):
        match = re.search(rf"(?<!\w){re.escape(alias_key)}(?!\w)", normalized_question)
        if not match:
            continue
        owners = alias_owners[alias_key]
        if len(owners) > 1:
            raise RelationshipQuestionError(
                f'Alias "{alias_key}" is ambiguous: {", ".join(sorted(owners))}'
            )
        canonical = next(iter(owners))
        positions[canonical] = min(positions.get(canonical, match.start()), match.start())

    if len(positions) == 1 and FIRST_PERSON.search(normalized_question):
        focal = [
            str(profile.get("name", "")).strip()
            for profile in profiles
            if profile.get("identity_type") == "persona"
        ]
        if len(focal) != 1:
            raise RelationshipQuestionError(
                "First-person relationship questions require exactly one focal persona."
            )
        positions.setdefault(focal[0], -1)

    if len(positions) < 2:
        raise RelationshipQuestionError(
            "Relationship questions must name two participants, or one participant with first-person wording."
        )
    if len(positions) > 2:
        raise RelationshipQuestionError(
            "Relationship question is ambiguous; name exactly two participants: "
            + ", ".join(sorted(positions))
        )
    ordered = sorted(positions, key=lambda name: (positions[name], name.casefold()))
    return by_name[ordered[0]], by_name[ordered[1]]


def _relationship_graph(
    dataset_dir: Path,
    profiles: list[dict],
    graph_loader: GraphLoader,
) -> tuple[set[str], list[dict]]:
    entities, relationships, _stats = graph_loader(dataset_dir, profiles=profiles)
    usable = [
        dict(item) for item in relationships
        if item.get("type") != "participant_in"
        and item.get("from") and item.get("to")
    ]
    return entities, usable


def _shortest_relationship_path(
    start: str,
    end: str,
    relationships: Sequence[dict],
) -> list[str] | None:
    adjacency: dict[str, set[str]] = defaultdict(set)
    for item in relationships:
        left = str(item["from"])
        right = str(item["to"])
        adjacency[left].add(right)
        adjacency[right].add(left)
    if start == end:
        return [start]
    queue = deque([(start, [start])])
    visited = {start}
    while queue:
        current, path = queue.popleft()
        for neighbor in sorted(adjacency.get(current, set()), key=str.casefold):
            if neighbor == end:
                return [*path, neighbor]
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append((neighbor, [*path, neighbor]))
    return None


def _edge_score(edge: dict, question: str) -> tuple[int, float, str]:
    relation = str(edge.get("type", ""))
    searchable = _key(RELATION_SEARCH_TERMS.get(relation, relation.replace("_", " ")))
    question_words = set(re.findall(r"\w+", _key(question)))
    relation_words = set(re.findall(r"\w+", searchable))
    lexical = len(question_words & relation_words)
    authority = 1 if edge.get("authority") == "user" else 0
    confidence = float(edge.get("confidence", 0.0) or 0.0)
    return authority * 100 + lexical, confidence, relation


def _path_edges(path: list[str], relationships: Sequence[dict], question: str) -> list[dict]:
    if len(path) == 2:
        direct = [
            item for item in relationships
            if {str(item.get("from")), str(item.get("to"))} == {path[0], path[1]}
        ]
        return sorted(direct, key=lambda item: _edge_score(item, question), reverse=True)

    selected = []
    for left, right in zip(path, path[1:]):
        candidates = [
            item for item in relationships
            if {str(item.get("from")), str(item.get("to"))} == {left, right}
        ]
        selected.append(max(candidates, key=lambda item: _edge_score(item, question)))
    return selected


def _persisted_evidence(
    dataset_dir: Path,
    participants: set[str],
) -> tuple[list[Evidence], dict[str, str]]:
    results = []
    source_origins = {}
    for source_path in sorted(dataset_dir.joinpath("sources").glob("*.jsonl")):
        with source_path.open(encoding="utf-8") as source:
            for line_number, line in enumerate(source, 1):
                try:
                    message = json.loads(line)
                except (json.JSONDecodeError, TypeError):
                    continue
                metadata = message.get("metadata", {})
                if not isinstance(metadata, dict):
                    metadata = {}
                sender = str(metadata.get("sender", "")).strip()
                subject = str(metadata.get("subject", "")).strip()
                if sender not in participants and subject not in participants:
                    continue
                content = re.sub(r"\s+", " ", str(message.get("content", ""))).strip()
                if not content:
                    continue
                confidence = metadata.get("confidence")
                item = Evidence(
                    message_id=f"{source_path.name}:{line_number}",
                    sender=subject or sender,
                    source_file=source_path.name,
                    timestamp=message.get("timestamp"),
                    excerpt=content[:500],
                    score=0.95,
                    source_type=str(message.get("source_type", "")),
                    record_kind=str(metadata.get("record_kind", "")),
                    authority=str(metadata.get("authority", "")),
                    authored_by=str(metadata.get("authored_by", sender)),
                    confidence=float(confidence) if isinstance(confidence, (int, float)) else None,
                    imported_at=str(metadata.get("imported_at", "")),
                )
                results.append(item)
                source_origins[item.message_id] = str(message.get("source_file", ""))
    return results, source_origins


def _same_source(
    edge: dict,
    evidence: Evidence,
    source_origins: dict[str, str],
) -> bool:
    source = str(edge.get("source", "")).casefold().strip()
    if not source or source.startswith("correction:"):
        return False
    if evidence.source_file.casefold() == source:
        return True
    return source_origins.get(evidence.message_id, "").casefold().strip() == source


def _support_for_edge(
    dataset_dir: Path,
    edge: dict,
    records: Sequence[Evidence],
    source_origins: dict[str, str],
) -> list[Evidence]:
    correction_id = str(edge.get("correction_id", ""))
    if correction_id:
        items = correction_evidence(
            dataset_dir,
            str(edge.get("from", "")),
            set(),
            limit=100,
        )
        return [item for item in items if item.message_id == f"correction:{correction_id}"][:1]

    same_source = [item for item in records if _same_source(edge, item, source_origins)]
    timestamp = str(edge.get("timestamp", "") or "")
    exact = [
        item for item in same_source
        if timestamp and item.timestamp
        and (
            str(item.timestamp) == timestamp
            or str(item.timestamp).startswith(timestamp)
            or timestamp.startswith(str(item.timestamp))
        )
    ]
    if exact:
        return exact[:1]
    endpoints = {str(edge.get("from", "")), str(edge.get("to", ""))}
    if edge.get("type") == "communicates_with":
        selected = []
        for endpoint in sorted(endpoints, key=str.casefold):
            match = next((item for item in same_source if item.sender == endpoint), None)
            if match:
                selected.append(match)
        return selected[:2]
    relation_words = set(re.findall(r"\w+", _key(RELATION_SEARCH_TERMS.get(str(edge.get("type")), ""))))
    relevant = [
        item for item in same_source
        if set(re.findall(r"\w+", _key(item.excerpt))) & relation_words
    ]
    return (relevant or same_source)[:1]


def _graph_evidence(edge: dict) -> Evidence:
    subject = str(edge.get("from", ""))
    object_name = str(edge.get("to", ""))
    relation = str(edge.get("type", ""))
    claim_id = str(edge.get("claim_id", "")) or semantic_claim_id(subject, relation, object_name)
    authority = str(edge.get("authority", "")) or "extracted"
    return Evidence(
        message_id=f"graph:{claim_id}",
        sender=subject,
        source_file=str(edge.get("source", "")) or "knowledge_graph.sqlite3",
        timestamp=str(edge.get("timestamp", "")) or None,
        excerpt=f"Effective graph fact: {subject} --{relation}--> {object_name}.",
        score=float(edge.get("confidence", 0.0) or 0.0),
        source_type="user_correction" if authority == "user" else "knowledge_graph",
        record_kind="effective_relationship",
        authority=authority,
        authored_by=str(edge.get("authored_by", "")),
        confidence=float(edge.get("confidence", 0.0) or 0.0),
    )


def _relation_fact(
    edge: dict,
    graph_item: Evidence,
    support: Sequence[Evidence],
    language: str,
) -> str:
    subject = str(edge.get("from", ""))
    object_name = str(edge.get("to", ""))
    relation = str(edge.get("type", ""))
    label = RELATION_LABELS.get(relation, {}).get(language, relation.replace("_", " "))
    confidence = float(edge.get("confidence", 0.0) or 0.0)
    if language == "es":
        provenance = "corrección del usuario" if edge.get("authority") == "user" else "grafo extraído"
    else:
        provenance = "user correction" if edge.get("authority") == "user" else "extracted graph"
    if language == "es":
        base = (
            f"{subject} {label} {object_name} en el grafo efectivo "
            f"(confianza {confidence:.2f}; procedencia: {provenance})."
        )
    else:
        base = (
            f"{subject} {label} {object_name} in the effective graph "
            f"(confidence {confidence:.2f}; provenance: {provenance})."
        )
    markers = " ".join(f"[{item.message_id}]" for item in [graph_item, *support])
    return f"{base} {markers}".strip()


def _relationship_abstention(
    left: str,
    right: str,
    language: str,
    *,
    reason: str,
    summary: dict[str, Any],
) -> Answer:
    text = (
        f"No encontré una relación respaldada entre {left} y {right}."
        if language == "es"
        else f"I found no supported relationship between {left} and {right}."
    )
    return Answer(
        text=text,
        citations=(),
        confidence=0.0,
        entities=(left, right),
        retrieval_summary={**summary, "abstention_reason": reason},
        abstained=True,
    )


def _wiki_relationship_mentions(dataset_dir: Path, names: Sequence[str]) -> int:
    path = dataset_dir / "wiki" / "relationships.md"
    try:
        content = _key(path.read_text(encoding="utf-8"))
    except OSError:
        return 0
    return sum(content.count(_key(name)) for name in names)


def answer_about_relationship(
    dataset_dir: Path,
    question: str,
    provider: LLMProvider,
    *,
    limit: int = 5,
    evidence_budget: int = 2500,
    memory_search: MemorySearch = query_memory.search_memory,
    graph_loader: GraphLoader = query_kg._load_kg,
) -> Answer:
    """Answer one two-person relationship question from the effective graph and sources."""
    left_profile, right_profile = resolve_relationship_participants(dataset_dir, question)
    left = str(left_profile.get("name", "")).strip()
    right = str(right_profile.get("name", "")).strip()
    language = detect_language(question)
    profiles = load_profiles(dataset_dir)
    _entities, relationships = _relationship_graph(dataset_dir, profiles, graph_loader)
    path = _shortest_relationship_path(left, right, relationships)
    summary: dict[str, Any] = {
        "answer_mode": "relationship",
        "participant_filters": [left, right],
        "effective_relationships": len(relationships),
        "provider": provider.name,
        "hosted": provider.hosted,
    }
    if not path:
        return _relationship_abstention(
            left,
            right,
            language,
            reason="no_supported_relationship_path",
            summary=summary,
        )

    edges = _path_edges(path, relationships, question)
    records, source_origins = _persisted_evidence(dataset_dir, set(path))
    endpoint_records = [item for item in records if item.sender in {left, right}]
    selected: list[Evidence] = []
    facts: list[str] = []

    def add(item: Evidence) -> None:
        if not any(existing.message_id == item.message_id for existing in selected):
            selected.append(item)

    for edge in edges:
        graph_item = _graph_evidence(edge)
        support = _support_for_edge(dataset_dir, edge, records, source_origins)
        if not support:
            return _relationship_abstention(
                left,
                right,
                language,
                reason="relationship_missing_source_evidence",
                summary={**summary, "kg_path": path},
            )
        add(graph_item)
        for item in support:
            add(item)
        facts.append(_relation_fact(edge, graph_item, support, language))

    temporal = sorted(
        (item for item in endpoint_records if item.timestamp),
        key=lambda item: (str(item.timestamp), item.message_id),
    )
    if temporal:
        first = temporal[0]
        last = temporal[-1]
        add(first)
        add(last)
        markers = f"[{first.message_id}]"
        if last.message_id != first.message_id:
            markers += f" [{last.message_id}]"
        period = f"{first.timestamp} — {last.timestamp}"
        facts.append(
            (f"Período de evidencia observado para ambos participantes: {period}. {markers}")
            if language == "es"
            else f"Observed evidence period for both participants: {period}. {markers}"
        )
    else:
        period = None

    relation_query = question + " " + " ".join(
        RELATION_SEARCH_TERMS.get(str(edge.get("type", "")), "") for edge in edges
    )
    for participant in (left, right):
        if len(selected) >= limit:
            break
        try:
            memories, _memory_summary = retrieve_evidence(
                dataset_dir,
                relation_query,
                participant,
                limit=max(1, min(2, limit)),
                evidence_budget=evidence_budget,
                memory_search=memory_search,
            )
        except (RuntimeError, OSError):
            memories = []
        for item in memories:
            if len(selected) < limit:
                add(item)

    if len(selected) > limit:
        mandatory_ids = {
            marker
            for fact in facts
            for marker in re.findall(r"\[([^\]]+)\]", fact)
        }
        mandatory = [item for item in selected if item.message_id in mandatory_ids]
        optional = [item for item in selected if item.message_id not in mandatory_ids]
        selected = [*mandatory, *optional[: max(0, limit - len(mandatory))]]

    consumed = sum(len(item.excerpt) for item in selected)
    if consumed > evidence_budget:
        per_item = evidence_budget // len(selected)
        if per_item < 40:
            return _relationship_abstention(
                left,
                right,
                language,
                reason="evidence_budget_too_small_for_path",
                summary={**summary, "kg_path": path, "required_chars": consumed},
            )
        selected = [replace(item, excerpt=item.excerpt[:per_item]) for item in selected]
        consumed = sum(len(item.excerpt) for item in selected)

    context = {
        "answer_mode": "relationship",
        "entities": [left, right],
        "relationship_hops": len(path) - 1,
        "relationship_path": [
            {
                "from": edge.get("from"),
                "type": edge.get("type"),
                "label": RELATION_LABELS.get(str(edge.get("type", "")), {}).get(
                    language,
                    str(edge.get("type", "")).replace("_", " "),
                ),
                "to": edge.get("to"),
                "confidence": edge.get("confidence"),
                "authority": edge.get("authority", "extracted"),
            }
            for edge in edges
        ],
        "observed_period": period,
        "wiki_relationship_mentions": _wiki_relationship_mentions(dataset_dir, (left, right)),
    }
    output = provider.generate(
        question,
        f"{left} ↔ {right}",
        selected,
        context,
        language=language,
    )
    provider_citations = _validate_output(output, selected) if not output.abstained else ()
    inferences = () if output.abstained else (output.text,)
    facts_heading = "Hechos" if language == "es" else "Facts"
    inference_heading = "Interpretación" if language == "es" else "Interpretation"
    lines = [f"{facts_heading}:", *(f"- {fact}" for fact in facts)]
    if inferences:
        lines.extend((f"{inference_heading}:", *(f"- {item}" for item in inferences)))

    fact_ids = {
        marker for fact in facts for marker in re.findall(r"\[([^\]]+)\]", fact)
    }
    used_ids = fact_ids | {item.message_id for item in provider_citations}
    citations = tuple(item for item in selected if item.message_id in used_ids)
    graph_confidence = min(float(edge.get("confidence", 0.0) or 0.0) for edge in edges)
    confidence = graph_confidence if output.abstained else min(graph_confidence, output.confidence)
    return Answer(
        text="\n".join(lines),
        citations=citations,
        confidence=max(0.0, min(1.0, confidence)),
        entities=(left, right),
        retrieval_summary={
            **summary,
            "kg_path": path,
            "kg_hops": len(path) - 1,
            "path_relationships": [str(edge.get("type", "")) for edge in edges],
            "selected_results": len(selected),
            "evidence_chars": consumed,
            "observed_period": period,
            "wiki_relationship_mentions": context["wiki_relationship_mentions"],
        },
        facts=tuple(facts),
        inferences=inferences,
    )
