"""Convert active corrections into participant-isolated grounded evidence."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from lazograph.domain.answer import Evidence

from .ledger import active_corrections


_RELATION_LABELS = {
    "sibling_of": "sibling brother sister hermano hermana",
    "cousin_of": "cousin primo prima",
    "friend_of": "friend amigo amiga",
    "romantic_partner": "romantic partner boyfriend girlfriend pareja novio novia",
    "coworker_of": "coworker colleague trabajo colega compañero compañera",
    "spouse_of": "spouse husband wife esposo esposa cónyuge",
    "parent_of": "parent father mother padre madre",
    "child_of": "child son daughter hijo hija",
    "manager_of": "manager boss jefe jefa",
    "communicates_with": "communicates conversation habla comunicación",
}


def _key(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _words(value: str) -> set[str]:
    return {
        word for word in re.findall(r"[a-z0-9_]+", _key(value))
        if len(word) > 2
    }


def correction_evidence(
    dataset_dir: Path,
    participant: str,
    question_terms: set[str],
    *,
    limit: int,
) -> list[Evidence]:
    """Return only active corrections relevant to this participant and question."""
    participant_key = _key(participant).strip()
    results = []
    for record in reversed(active_corrections(dataset_dir)):
        assertion = record["assert"]
        retraction = record["retract"]
        endpoints = {
            _key(str(assertion.get("subject", ""))).strip(),
            _key(str(assertion.get("object", ""))).strip(),
        }
        if participant_key not in endpoints:
            continue
        labels = " ".join((
            _RELATION_LABELS.get(str(assertion.get("predicate", "")), ""),
            _RELATION_LABELS.get(str(retraction.get("predicate", "")), ""),
        ))
        searchable = " ".join((
            str(assertion.get("subject", "")),
            str(assertion.get("predicate", "")),
            str(assertion.get("object", "")),
            str(retraction.get("predicate", "")),
            labels,
            str(record.get("raw_text", "")),
        ))
        if question_terms and not (_words(searchable) & {_key(term) for term in question_terms}):
            continue
        excerpt = (
            f'User correction: {assertion["subject"]} --{assertion["predicate"]}--> '
            f'{assertion["object"]}; retracted {retraction["predicate"]}. '
            f'Instruction: {record["raw_text"]}'
        )
        results.append(Evidence(
            message_id=f'correction:{record["claim_id"]}',
            sender=participant,
            source_file="corrections/ledger.jsonl",
            timestamp=str(record.get("created_at", "")) or None,
            excerpt=excerpt[:500],
            score=1.0,
            source_type="user_correction",
            record_kind="correction",
            authority="user",
            authored_by="dataset_owner",
            confidence=1.0,
            imported_at=str(record.get("created_at", "")),
        ))
        if len(results) >= limit:
            break
    return results
