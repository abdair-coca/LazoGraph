"""Conservative correction parsing, entity resolution, and dry-run planning."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path

from lazograph.domain.correction import Claim, CorrectionPreview, SYMMETRIC_RELATIONS
from scripts import query_kg


class CorrectionValidationError(ValueError):
    """A correction is unsupported, ambiguous, or does not match effective knowledge."""


_RELATIONS = {
    "brother": "sibling_of",
    "sister": "sibling_of",
    "sibling": "sibling_of",
    "hermano": "sibling_of",
    "hermana": "sibling_of",
    "cousin": "cousin_of",
    "primo": "cousin_of",
    "prima": "cousin_of",
    "friend": "friend_of",
    "amigo": "friend_of",
    "amiga": "friend_of",
    "romantic partner": "romantic_partner",
    "partner": "romantic_partner",
    "boyfriend": "romantic_partner",
    "girlfriend": "romantic_partner",
    "pareja": "romantic_partner",
    "novio": "romantic_partner",
    "novia": "romantic_partner",
    "coworker": "coworker_of",
    "co worker": "coworker_of",
    "colleague": "coworker_of",
    "companero de trabajo": "coworker_of",
    "companera de trabajo": "coworker_of",
    "colega": "coworker_of",
    "spouse": "spouse_of",
    "husband": "spouse_of",
    "wife": "spouse_of",
    "esposo": "spouse_of",
    "esposa": "spouse_of",
    "conyuge": "spouse_of",
    "father": "parent_of",
    "mother": "parent_of",
    "parent": "parent_of",
    "padre": "parent_of",
    "madre": "parent_of",
    "son": "child_of",
    "daughter": "child_of",
    "child": "child_of",
    "hijo": "child_of",
    "hija": "child_of",
    "boss": "manager_of",
    "manager": "manager_of",
    "jefe": "manager_of",
    "jefa": "manager_of",
}

_ENGLISH = re.compile(
    r"^(?P<subject>.+?)\s+is\s+(?P<object>.+?)[’']s\s+(?P<new>.+?)"
    r"\s*[,;]\s*not\s+(?:his|her|their|the)\s+(?P<old>.+?)\.?$",
    re.IGNORECASE,
)
_SPANISH = re.compile(
    r"^(?P<subject>.+?)\s+no\s+es\s+(?P<old>.+?)\s+de\s+(?P<object>.+?)"
    r"\s*[,;]\s*(?:es\s+)?su\s+(?P<new>.+?)\.?$",
    re.IGNORECASE,
)
_MAX_CORRECTION_LENGTH = 2000


def _key(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", normalized).strip(" .,:;\t\r\n")


def _relation(value: str) -> str:
    normalized = _key(value)
    normalized = re.sub(
        r"^(?:a|an|the|el|la|los|las|un|una|his|her|their|su)\s+",
        "",
        normalized,
    )
    canonical = _RELATIONS.get(normalized)
    if canonical:
        return canonical
    supported = ", ".join(sorted(set(_RELATIONS.values())))
    raise CorrectionValidationError(
        f'Unsupported relationship "{value.strip()}". Supported types: {supported}'
    )


def _parse(text: str) -> tuple[str, str, str, str]:
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        raise CorrectionValidationError("Correction text cannot be empty.")
    if len(normalized) > _MAX_CORRECTION_LENGTH:
        raise CorrectionValidationError("Correction text exceeds the 2000-character limit.")
    match = _ENGLISH.match(normalized) or _SPANISH.match(normalized)
    if not match:
        raise CorrectionValidationError(
            "Unsupported correction syntax. Use: "
            '"Carlos is Juan\'s cousin, not his brother" or '
            '"Carlos no es hermano de Juan, es su primo".'
        )
    old_relation = _relation(match.group("old"))
    new_relation = _relation(match.group("new"))
    if old_relation == new_relation:
        raise CorrectionValidationError("Retracted and asserted relationships are identical.")
    return (
        match.group("subject").strip(),
        match.group("object").strip(),
        old_relation,
        new_relation,
    )


def _profile_aliases(profile: dict) -> set[str]:
    aliases = {str(profile.get("name", "")).strip()}
    raw_aliases = profile.get("aliases", [])
    if isinstance(raw_aliases, list):
        aliases.update(str(alias).strip() for alias in raw_aliases)
    return {alias for alias in aliases if alias}


def _resolve_entity_strict(
    query: str,
    entities: set[str],
    profiles: list[dict],
) -> str:
    normalized = _key(query)
    candidates: set[str] = set()
    for entity in entities:
        if _key(entity) == normalized:
            candidates.add(entity)
    for profile in profiles:
        canonical = str(profile.get("name", "")).strip()
        if canonical and any(_key(alias) == normalized for alias in _profile_aliases(profile)):
            entity_matches = [entity for entity in entities if _key(entity) == _key(canonical)]
            candidates.update(entity_matches or [canonical])
    if not candidates:
        for entity in entities:
            entity_key = _key(entity)
            if normalized in entity_key or entity_key in normalized:
                candidates.add(entity)
    if len(candidates) == 1:
        return next(iter(candidates))
    if not candidates:
        raise CorrectionValidationError(f'No entity matching "{query}".')
    raise CorrectionValidationError(
        f'Entity "{query}" is ambiguous. Matches: '
        + ", ".join(sorted(candidates, key=str.casefold))
    )


def _same_claim(
    relationship: dict,
    subject: str,
    predicate: str,
    object_name: str,
) -> bool:
    if str(relationship.get("type", "")).casefold() != predicate.casefold():
        return False
    source = str(relationship.get("from", ""))
    target = str(relationship.get("to", ""))
    if predicate in SYMMETRIC_RELATIONS:
        return {_key(source), _key(target)} == {_key(subject), _key(object_name)}
    return _key(source) == _key(subject) and _key(target) == _key(object_name)


def _claim_from_relationship(relationship: dict) -> Claim:
    raw_confidence = relationship.get("confidence", 0.0)
    confidence = float(raw_confidence) if isinstance(raw_confidence, (int, float)) else 0.0
    claim_value = "|".join((
        str(relationship.get("from", "")).casefold(),
        str(relationship.get("type", "")).casefold(),
        str(relationship.get("to", "")).casefold(),
        str(relationship.get("source", "")),
        str(relationship.get("timestamp", "")),
    ))
    claim_id = str(relationship.get("claim_id", "")) or (
        "base-" + hashlib.sha256(claim_value.encode("utf-8")).hexdigest()[:16]
    )
    return Claim(
        subject=str(relationship.get("from", "")),
        predicate=str(relationship.get("type", "")),
        object=str(relationship.get("to", "")),
        confidence=confidence,
        source=str(relationship.get("source", "")),
        claim_id=claim_id,
    )


def build_correction_preview(text: str, dataset_dir: Path) -> CorrectionPreview:
    """Resolve a natural-language relation correction without writing."""
    raw_subject, raw_object, old_relation, new_relation = _parse(text)
    profiles = query_kg._load_participant_profiles(dataset_dir)
    entities, relationships, _stats = query_kg._load_kg(dataset_dir, profiles=profiles)
    subject = _resolve_entity_strict(raw_subject, entities, profiles)
    object_name = _resolve_entity_strict(raw_object, entities, profiles)
    if _key(subject) == _key(object_name):
        raise CorrectionValidationError("Correction subject and object resolve to the same entity.")

    matched = tuple(
        _claim_from_relationship(relationship)
        for relationship in relationships
        if _same_claim(relationship, subject, old_relation, object_name)
    )
    fingerprint_value = "|".join((
        _key(subject), old_relation, _key(object_name), new_relation,
    ))
    fingerprint = "sha256:" + hashlib.sha256(fingerprint_value.encode("utf-8")).hexdigest()
    from .ledger import find_active_by_fingerprint

    active = find_active_by_fingerprint(dataset_dir, fingerprint)
    if active:
        return CorrectionPreview(
            raw_text=re.sub(r"\s+", " ", text).strip(),
            dataset_slug=dataset_dir.name,
            dataset_dir=dataset_dir,
            fingerprint=fingerprint,
            retract=Claim(subject, old_relation, object_name, 1.0, "user_correction"),
            assert_claim=Claim(subject, new_relation, object_name, 1.0, "user_correction"),
            matched_claims=(),
            already_applied=True,
        )
    if not matched:
        raise CorrectionValidationError(
            f"No effective {old_relation} claim connects {subject} and {object_name}."
        )
    return CorrectionPreview(
        raw_text=re.sub(r"\s+", " ", text).strip(),
        dataset_slug=dataset_dir.name,
        dataset_dir=dataset_dir,
        fingerprint=fingerprint,
        retract=Claim(subject, old_relation, object_name, 1.0, "user_correction"),
        assert_claim=Claim(subject, new_relation, object_name, 1.0, "user_correction"),
        matched_claims=matched,
    )


def apply_correction(preview: CorrectionPreview) -> dict:
    """Revalidate immediately, then append one correction event or return a no-op."""
    dataset_dir = preview.dataset_dir
    current = build_correction_preview(preview.raw_text, dataset_dir)
    if current.fingerprint != preview.fingerprint:
        raise CorrectionValidationError("Correction changed after preflight; run it again.")
    from .ledger import append_correction

    return append_correction(dataset_dir, current)
