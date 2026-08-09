"""Parsing and non-mutating preflight for user-provided context."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from lazograph.domain.identity import IdentityResolutionError, load_profiles, resolve_participant
from scripts import ingest


class ContextValidationError(ValueError):
    """Manual context cannot be interpreted safely."""


@dataclass(frozen=True)
class ContextRecord:
    number: int
    kind: str
    subject: str
    content: str
    confidence: float
    authority: str
    duplicate: bool


@dataclass(frozen=True)
class ContextPreview:
    source: Path
    dataset_dir: Path
    source_sha256: str
    records: tuple[ContextRecord, ...]
    pii_flags: tuple[str, ...]

    @property
    def duplicates(self) -> int:
        return sum(record.duplicate for record in self.records)

    @property
    def new_records(self) -> int:
        return len(self.records) - self.duplicates


_PREFIXES = {
    "assert": ("assertion", 1.0, "user_assertion"),
    "assertion": ("assertion", 1.0, "user_assertion"),
    "fact": ("assertion", 1.0, "user_assertion"),
    "hecho": ("assertion", 1.0, "user_assertion"),
    "afirmacion": ("assertion", 1.0, "user_assertion"),
    "context": ("freeform", 0.75, "user_context"),
    "contexto": ("freeform", 0.75, "user_context"),
    "note": ("freeform", 0.75, "user_context"),
    "nota": ("freeform", 0.75, "user_context"),
    "inference": ("inference", 0.5, "user_inference"),
    "inferencia": ("inference", 0.5, "user_inference"),
}
_PREFIX_PATTERN = re.compile(r"^([\wÁÉÍÓÚÜÑáéíóúüñ]+)\s*:\s*(.*)$", re.DOTALL)
_MAX_SOURCE_BYTES = 10 * 1024 * 1024


def _key(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = "".join(
        char for char in unicodedata.normalize("NFKD", normalized)
        if not unicodedata.combining(char)
    )
    return re.sub(r"\s+", " ", normalized).strip()


def _blocks(text: str) -> list[str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return [re.sub(r"\s+", " ", block).strip() for block in re.split(r"\n\s*\n", normalized) if block.strip()]


def _classify(block: str) -> tuple[str, float, str, str]:
    match = _PREFIX_PATTERN.match(block)
    if match:
        prefix = _key(match.group(1))
        if prefix in _PREFIXES:
            content = match.group(2).strip()
            if not content:
                raise ContextValidationError(f'Context block "{match.group(1)}:" is empty.')
            kind, confidence, authority = _PREFIXES[prefix]
            return kind, confidence, authority, content
    return "freeform", 0.75, "user_context", block


def _aliases(profile: dict) -> set[str]:
    values = {str(profile.get("name", "")).strip()}
    raw_aliases = profile.get("aliases", [])
    if isinstance(raw_aliases, list):
        values.update(str(alias).strip() for alias in raw_aliases)
    return {value for value in values if value}


def _mentions(content: str, profiles: list[dict]) -> list[str]:
    haystack = f" {_key(content)} "
    matches = []
    for profile in profiles:
        name = str(profile.get("name", "")).strip()
        if not name:
            continue
        for alias in _aliases(profile):
            needle = _key(alias)
            if len(needle) >= 2 and re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", haystack):
                matches.append(name)
                break
    return sorted(set(matches), key=str.casefold)


def _subject_for(
    content: str,
    profiles: list[dict],
    forced_subject: str | None,
) -> str:
    if forced_subject:
        return forced_subject
    matches = _mentions(content, profiles)
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise ContextValidationError(
            "A context block does not identify a known participant. Pass --about explicitly."
        )
    raise ContextValidationError(
        "A context block mentions multiple participants: "
        + ", ".join(matches)
        + ". Split it or pass --about explicitly."
    )


def _message(
    record: ContextRecord,
    *,
    source: Path,
    source_sha256: str,
    imported_at: str,
) -> dict:
    return {
        "role": "user",
        "content": record.content,
        "timestamp": imported_at,
        "source_file": source.name,
        "source_type": "user_context",
        "metadata": {
            "sender": record.subject,
            "subject": record.subject,
            "authored_by": "dataset_owner",
            "record_kind": record.kind,
            "authority": record.authority,
            "confidence": record.confidence,
            "source_sha256": source_sha256,
            "record_number": record.number,
        },
    }


def build_context_preview(
    source_path: str | Path,
    dataset_dir: Path,
    *,
    about: str | None = None,
    now: datetime | None = None,
) -> ContextPreview:
    """Parse, classify, resolve subjects, scan PII, and deduplicate without writes."""
    source = Path(source_path).expanduser()
    if not source.is_file():
        raise ContextValidationError(f"Context source not found: {source}")
    if source.stat().st_size > _MAX_SOURCE_BYTES:
        raise ContextValidationError("Context source exceeds the 10 MiB safety limit.")
    try:
        raw = source.read_bytes()
        text = raw.decode("utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        raise ContextValidationError("Context source must be readable UTF-8 text.") from exc
    if "\x00" in text:
        raise ContextValidationError("Context source appears to be binary.")

    blocks = _blocks(text)
    if not blocks:
        raise ContextValidationError("Context source contains no records.")
    try:
        profiles = load_profiles(dataset_dir)
        forced_subject = (
            str(resolve_participant(dataset_dir, about).get("name", "")).strip()
            if about else None
        )
    except IdentityResolutionError as exc:
        raise ContextValidationError(str(exc)) from exc

    source_sha256 = "sha256:" + hashlib.sha256(raw).hexdigest()
    imported_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
    existing_hashes = ingest._load_existing_hashes(dataset_dir)
    seen = set(existing_hashes)
    records = []
    messages = []
    for number, block in enumerate(blocks, 1):
        kind, confidence, authority, content = _classify(block)
        subject = _subject_for(content, profiles, forced_subject)
        provisional = ContextRecord(
            number=number,
            kind=kind,
            subject=subject,
            content=content,
            confidence=confidence,
            authority=authority,
            duplicate=False,
        )
        message = _message(
            provisional,
            source=source,
            source_sha256=source_sha256,
            imported_at=imported_at,
        )
        fingerprint = ingest._content_hash(message)
        duplicate = fingerprint in seen
        seen.add(fingerprint)
        record = ContextRecord(**{**provisional.__dict__, "duplicate": duplicate})
        records.append(record)
        messages.append(_message(record, source=source, source_sha256=source_sha256, imported_at=imported_at))

    return ContextPreview(
        source=source.resolve(),
        dataset_dir=dataset_dir,
        source_sha256=source_sha256,
        records=tuple(records),
        pii_flags=tuple(sorted(ingest.scan_pii(messages))),
    )
