"""Grounded relationship descriptions with chronology and safe interpretation."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from lazograph.domain.answer import Answer, Evidence
from lazograph.domain.identity import load_profiles
from lazograph.features.ask_person.service import (
    MemorySearch,
    _validate_output,
    detect_language,
    retrieve_evidence,
)
from lazograph.features.ask_relationship.service import (
    RELATION_LABELS,
    GraphLoader,
    _graph_evidence,
    _path_edges,
    _persisted_evidence,
    _relationship_graph,
    _shortest_relationship_path,
    _support_for_edge,
    resolve_relationship_participants,
)
from lazograph.ports.llm import LLMProvider
from scripts import query_kg, query_memory


_DESCRIPTION_QUESTION = re.compile(
    r"\b(?:describe|describir|describirías|describirias|characterize|caracterizar|"
    r"summarize|resumir)\b.{0,80}\b(?:relationship|relation|relación|relacion|"
    r"vínculo|vinculo|between|with|entre|con)\b|"
    r"\b(?:relationship|relation|relación|relacion|vínculo|vinculo)\b.{0,60}\b"
    r"(?:describe|describir|characterize|caracterizar|summary|resumen)\b",
    re.IGNORECASE,
)
_UNSAFE_DIAGNOSTIC = re.compile(
    r"\b(?:diagnos(?:is|e|ed|tic)?|mental\s+illness|depression|anxiety|ptsd|"
    r"bipolar|narciss(?:ist|istic)|psychopath|personality\s+disorder|toxic|abusive|"
    r"diagnóstico|depresión|ansiedad|trastorno|narcisista|psicópata|tóxic[oa]|"
    r"abusiv[oa])\b",
    re.IGNORECASE,
)
_POSITIVE = re.compile(
    r"\b(?:like|likes|love|loves|enjoy|enjoys|care|cares|support|supports|"
    r"friend|friends|friendship|partner|partners|happy|thanks|thank|"
    r"gusta|gustan|encanta|encantan|quiero|queremos|apoyo|apoya|amig[oa]s?|"
    r"amistad|pareja|feliz|gracias|cariño|carino)\b",
    re.IGNORECASE,
)
_NEGATIVE = re.compile(
    r"\b(?:hate|hates|dislike|dislikes|argue|argues|argument|conflict|"
    r"argued|angry|anger|problem|problems|fight|fights|block(?:ed|s)?|avoid|avoids|"
    r"do\s+not\s+like|does\s+not\s+like|"
    r"odio|odias|no\s+me\s+gust|discusi[oó]n|conflict[oa]s?|enojad[oa]?|"
    r"problema[s]?|pelea[s]?|bloquead[oa]?|evit[ao])\b",
    re.IGNORECASE,
)


def is_relationship_description_question(question: str) -> bool:
    """Recognize summary requests without resolving participant identity."""
    return bool(_DESCRIPTION_QUESTION.search(question))


def _abstention(
    left: str,
    right: str,
    language: str,
    *,
    reason: str,
    summary: dict[str, Any],
    text: str | None = None,
) -> Answer:
    if text is None:
        text = (
            f"No puedo describir de forma segura la relación entre {left} y {right}."
            if language == "es"
            else f"I cannot safely describe the relationship between {left} and {right}."
        )
    return Answer(
        text=text,
        citations=(),
        confidence=0.0,
        entities=(left, right) if left and right else (),
        retrieval_summary={**summary, "abstention_reason": reason},
        abstained=True,
    )


def _signals(item: Evidence) -> set[str]:
    signals = set()
    if _POSITIVE.search(item.excerpt):
        signals.add("positive")
    if _NEGATIVE.search(item.excerpt):
        signals.add("negative")
    return signals


def _period(records: Sequence[Evidence]) -> tuple[str | None, str | None]:
    dated = sorted(
        (item for item in records if item.timestamp),
        key=lambda item: (str(item.timestamp), item.message_id),
    )
    if not dated:
        return None, None
    return str(dated[0].timestamp), str(dated[-1].timestamp)


def _coverage_fact(
    records: Sequence[Evidence],
    language: str,
) -> tuple[str, str | None, str | None]:
    start, end = _period(records)
    source_count = len({item.source_file for item in records})
    if start and end:
        period = f"{start} — {end}"
        markers = f"[{records[0].message_id}] [{records[-1].message_id}]"
    else:
        period = "unknown" if language == "en" else "desconocido"
        markers = ""
    if language == "es":
        fact = (
            f"Período analizado: {period}; cobertura: {len(records)} mensajes persistidos "
            f"en {source_count} fuente(s). {markers}"
        )
    else:
        fact = (
            f"Analyzed period: {period}; coverage: {len(records)} persisted messages "
            f"across {source_count} source(s). {markers}"
        )
    return fact.strip(), start, end


def _observation(item: Evidence, label: str, language: str) -> str:
    prefix = {
        ("positive", "es"): "Observación positiva",
        ("negative", "es"): "Observación negativa",
        ("positive", "en"): "Positive observation",
        ("negative", "en"): "Negative observation",
    }[(label, language)]
    return f'{prefix}: "{item.excerpt}" [{item.message_id}]'


def _safe_provider_output(output) -> bool:
    return output.abstained or not _UNSAFE_DIAGNOSTIC.search(output.text)


def answer_describe_relationship(
    dataset_dir: Path,
    question: str,
    provider: LLMProvider,
    *,
    limit: int = 5,
    evidence_budget: int = 2500,
    memory_search: MemorySearch = query_memory.search_memory,
    graph_loader: GraphLoader = query_kg._load_kg,
) -> Answer:
    """Describe one relationship from effective, participant-filtered evidence."""
    language = detect_language(question)
    if _UNSAFE_DIAGNOSTIC.search(question):
        return _abstention(
            "",
            "",
            language,
            reason="unsafe_diagnostic_language",
            summary={"answer_mode": "relationship_description", "provider": provider.name},
            text=(
                "No puedo convertir conversaciones en diagnósticos o etiquetas clínicas."
                if language == "es"
                else "I cannot turn conversations into diagnoses or clinical labels."
            ),
        )

    left_profile, right_profile = resolve_relationship_participants(dataset_dir, question)
    left = str(left_profile.get("name", "")).strip()
    right = str(right_profile.get("name", "")).strip()
    profiles = load_profiles(dataset_dir)
    _entities, relationships = _relationship_graph(dataset_dir, profiles, graph_loader)
    path = _shortest_relationship_path(left, right, relationships)
    summary: dict[str, Any] = {
        "answer_mode": "relationship_description",
        "participant_filters": [left, right],
        "effective_relationships": len(relationships),
        "provider": provider.name,
        "hosted": provider.hosted,
    }
    if not path:
        return _abstention(
            left,
            right,
            language,
            reason="no_supported_relationship_path",
            summary=summary,
        )

    edges = _path_edges(path, relationships, question)
    records, source_origins = _persisted_evidence(dataset_dir, set(path))
    endpoint_names = {left, right}
    endpoint_records = sorted(
        (item for item in records if item.sender in endpoint_names),
        key=lambda item: (str(item.timestamp or ""), item.message_id),
    )
    selected: list[Evidence] = []
    facts: list[str] = []

    def add(item: Evidence) -> None:
        if not any(existing.message_id == item.message_id for existing in selected):
            selected.append(item)

    for edge in edges:
        graph_item = _graph_evidence(edge)
        support = _support_for_edge(dataset_dir, edge, records, source_origins)
        if not support:
            return _abstention(
                left,
                right,
                language,
                reason="relationship_missing_source_evidence",
                summary={**summary, "kg_path": path},
            )
        add(graph_item)
        for item in support:
            if item.sender in endpoint_names:
                add(item)
        relation = str(edge.get("type", ""))
        label = RELATION_LABELS.get(relation, {}).get(language, relation.replace("_", " "))
        graph_id = graph_item.message_id.removeprefix("graph:")
        facts.append(f"{edge.get('from', '')} {label} {edge.get('to', '')} [{graph_item.message_id}]")
        if edge.get("authority") == "user":
            facts.append(
                "Active user correction changes the effective relationship evidence. "
                f"[graph:{graph_id}]"
                if language == "en"
                else "Una corrección activa del usuario cambia la evidencia relacional efectiva. "
                f"[graph:{graph_id}]"
            )

    if endpoint_records:
        coverage, start, end = _coverage_fact(endpoint_records, language)
        facts.insert(0, coverage)
        for item in {endpoint_records[0], endpoint_records[-1]}:
            add(item)
    else:
        start = end = None
        facts.insert(
            0,
            "Analyzed period and coverage are unknown."
            if language == "en"
            else "El período analizado y la cobertura son desconocidos.",
        )

    positive = [item for item in endpoint_records if "positive" in _signals(item)]
    negative = [item for item in endpoint_records if "negative" in _signals(item)]
    for item in [*positive[:2], *negative[:2]]:
        add(item)
    observations = tuple(
        _observation(item, label, language)
        for label, items in (("positive", positive[:2]), ("negative", negative[:2]))
        for item in items
    )
    if positive and negative:
        facts.append(
            (
                "Contradictory evidence: positive and negative signals both appear in the observed period. "
                f"[{positive[0].message_id}] [{negative[0].message_id}]"
                if language == "en"
                else "Evidencia contradictoria: aparecen señales positivas y negativas en el período observado. "
                f"[{positive[0].message_id}] [{negative[0].message_id}]"
            )
        )

    relation_query = question + " relationship description chronology"
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
            marker for fact in facts for marker in re.findall(r"\[([^\]]+)\]", fact)
        }
        mandatory_ids.update(
            marker
            for observation in observations
            for marker in re.findall(r"\[([^\]]+)\]", observation)
        )
        mandatory = [item for item in selected if item.message_id in mandatory_ids]
        optional = [item for item in selected if item.message_id not in mandatory_ids]
        selected = [*mandatory, *optional[: max(0, limit - len(mandatory))]]

    consumed = sum(len(item.excerpt) for item in selected)
    if selected and consumed > evidence_budget:
        per_item = evidence_budget // len(selected)
        if per_item < 40:
            return _abstention(
                left,
                right,
                language,
                reason="evidence_budget_too_small_for_description",
                summary={**summary, "kg_path": path, "required_chars": consumed},
            )
        selected = [replace(item, excerpt=item.excerpt[:per_item]) for item in selected]
        consumed = sum(len(item.excerpt) for item in selected)

    context = {
        "answer_mode": "relationship_description",
        "entities": [left, right],
        "relationship_hops": len(path) - 1,
        "relationship_path": [
            {
                "from": edge.get("from"),
                "type": edge.get("type"),
                "label": RELATION_LABELS.get(str(edge.get("type", "")), {}).get(
                    language, str(edge.get("type", "")).replace("_", " ")
                ),
                "to": edge.get("to"),
                "confidence": edge.get("confidence"),
                "authority": edge.get("authority", "extracted"),
            }
            for edge in edges
        ],
        "observed_period": f"{start} — {end}" if start and end else None,
        "evidence_coverage": {
            "messages": len(endpoint_records),
            "sources": len({item.source_file for item in endpoint_records}),
        },
        "positive_evidence_count": len(positive),
        "negative_evidence_count": len(negative),
        "contradictory_evidence": bool(positive and negative),
    }
    output = provider.generate(
        question,
        f"{left} ↔ {right}",
        selected,
        context,
        language=language,
    )
    if not _safe_provider_output(output):
        return _abstention(
            left,
            right,
            language,
            reason="unsafe_provider_output",
            summary={**summary, "kg_path": path},
        )
    if output.abstained:
        return _abstention(
            left,
            right,
            language,
            reason="provider_abstained",
            summary={**summary, "kg_path": path},
        )
    provider_citations = _validate_output(output, selected)
    unknowns = []
    if not positive:
        unknowns.append(
            "No positive signal was identified in selected messages."
            if language == "en" else "No se identificó señal positiva en mensajes seleccionados."
        )
    if not negative:
        unknowns.append(
            "No negative signal was identified in selected messages."
            if language == "en" else "No se identificó señal negativa en mensajes seleccionados."
        )
    facts_heading = "Observaciones" if language == "es" else "Observations"
    inference_heading = "Interpretación" if language == "es" else "Interpretation"
    unknown_heading = "Desconocido" if language == "es" else "Unknowns"
    lines = [
        f"{facts_heading}:",
        *(f"- {fact}" for fact in facts),
        *(f"- {item}" for item in observations),
        f"{inference_heading}:",
        f"- {output.text}",
    ]
    if unknowns:
        lines.extend((f"{unknown_heading}:", *(f"- {item}" for item in unknowns)))
    fact_ids = {
        marker
        for fact in [*facts, *observations]
        for marker in re.findall(r"\[([^\]]+)\]", fact)
    }
    used_ids = fact_ids | {item.message_id for item in provider_citations}
    citations = tuple(item for item in selected if item.message_id in used_ids)
    graph_confidence = min(float(edge.get("confidence", 0.0) or 0.0) for edge in edges)
    return Answer(
        text="\n".join(lines),
        citations=citations,
        confidence=max(0.0, min(1.0, min(graph_confidence, output.confidence))),
        entities=(left, right),
        retrieval_summary={
            **summary,
            "kg_path": path,
            "kg_hops": len(path) - 1,
            "path_relationships": [str(edge.get("type", "")) for edge in edges],
            "selected_results": len(selected),
            "evidence_chars": consumed,
            "observed_period": context["observed_period"],
            "evidence_coverage": context["evidence_coverage"],
            "positive_evidence": len(positive),
            "negative_evidence": len(negative),
            "contradictory_evidence": bool(positive and negative),
        },
        facts=tuple(facts),
        inferences=(output.text,),
        missing_information=tuple(unknowns),
    )
