"""Parsing and non-mutating preflight for user-provided context."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter
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
    imported_at: str
    records: tuple[ContextRecord, ...]
    pii_flags: tuple[str, ...]

    @property
    def duplicates(self) -> int:
        return sum(record.duplicate for record in self.records)

    @property
    def new_records(self) -> int:
        return len(self.records) - self.duplicates


@dataclass(frozen=True)
class ContextApplyResult:
    source_file: str | None
    stored_records: int
    duplicates: int
    vector_count: int
    invariants: dict


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
        imported_at=imported_at,
        records=tuple(records),
        pii_flags=tuple(sorted(ingest.scan_pii(messages))),
    )


def _preview_messages(preview: ContextPreview) -> list[dict]:
    return [
        _message(
            record,
            source=preview.source,
            source_sha256=preview.source_sha256,
            imported_at=preview.imported_at,
        )
        for record in preview.records
    ]


def _snapshot(paths: list[Path]) -> dict[Path, bytes | None]:
    return {path: path.read_bytes() if path.exists() else None for path in paths}


def _restore(snapshot: dict[Path, bytes | None]) -> None:
    for path, content in snapshot.items():
        if content is None:
            path.unlink(missing_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)


def _vector_ids(dataset_dir: Path) -> set[str]:
    try:
        from mempalace.palace import get_collection
    except ImportError as exc:
        raise RuntimeError(
            "mempalace is required for context apply; install it with: pip install mempalace"
        ) from exc
    collection = get_collection(
        str(dataset_dir / ".mempalace" / "palace"),
        create=True,
    )
    result = collection.get(where={"wing": dataset_dir.name}, include=[])
    return set(result.get("ids", []))


def _delete_vectors(dataset_dir: Path, vector_ids: set[str]) -> None:
    if not vector_ids:
        return
    from mempalace.palace import get_collection

    collection = get_collection(
        str(dataset_dir / ".mempalace" / "palace"),
        create=True,
    )
    collection.delete(ids=sorted(vector_ids))


def _kg_stats(dataset_dir: Path) -> dict[str, int]:
    try:
        payload = json.loads(dataset_dir.joinpath("dataset.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        payload = {}
    stats = payload.get("stats", {}) if isinstance(payload, dict) else {}
    return {
        "entities": int(stats.get("kg_entities", 0) or 0),
        "relationships": int(stats.get("kg_relationships", 0) or 0),
    }


def apply_context(preview: ContextPreview) -> ContextApplyResult:
    """Persist a validated preview and roll back all new artifacts on failure."""
    try:
        current_hash = "sha256:" + hashlib.sha256(preview.source.read_bytes()).hexdigest()
    except OSError as exc:
        raise ContextValidationError("Context source changed or became unreadable.") from exc
    if current_hash != preview.source_sha256:
        raise ContextValidationError("Context source changed after preflight; run it again.")

    existing_hashes = ingest._load_existing_hashes(preview.dataset_dir)
    messages, duplicates = ingest.dedup_messages(_preview_messages(preview), existing_hashes)
    if not messages:
        from scripts.dataset_invariants import validate_dataset

        invariants = validate_dataset(preview.dataset_dir)
        if not invariants["ok"]:
            raise RuntimeError("Existing dataset invariants failed; run diagnose before applying context.")
        return ContextApplyResult(None, 0, duplicates, 0, invariants)

    sources_dir = preview.dataset_dir / "sources"
    managed_paths = [
        preview.dataset_dir / "dataset.json",
        preview.dataset_dir / "participants.json",
        sources_dir / ".source-index.json",
    ]
    snapshot = _snapshot(managed_paths)
    sources_before = set(sources_dir.glob("*.jsonl"))
    vector_ids_before = _vector_ids(preview.dataset_dir)
    source_filename = None
    stored = 0
    try:
        stored = ingest._store_in_mempalace(
            preview.dataset_dir,
            preview.dataset_dir.name,
            messages,
        )
        kinds = Counter(message["metadata"]["record_kind"] for message in messages)
        source_filename = ingest._write_sources_backup(
            preview.dataset_dir,
            messages,
            "user_context",
            str(preview.source),
            set(preview.pii_flags),
            source_metadata={
                "source_sha256": preview.source_sha256,
                "authored_by": "dataset_owner",
                "authority": "mixed" if len(kinds) > 1 else messages[0]["metadata"]["authority"],
                "record_kinds": dict(sorted(kinds.items())),
            },
        )
        all_messages = ingest._load_stored_messages(preview.dataset_dir)
        ingest._write_participant_profiles(preview.dataset_dir, all_messages)
        ingest._replace_stats(preview.dataset_dir, all_messages, _kg_stats(preview.dataset_dir))

        from scripts.dataset_invariants import validate_dataset

        invariants = validate_dataset(preview.dataset_dir)
        if not invariants["ok"]:
            raise RuntimeError("Dataset invariants failed after context apply.")
        return ContextApplyResult(
            source_file=source_filename,
            stored_records=len(messages),
            duplicates=duplicates,
            vector_count=stored,
            invariants=invariants,
        )
    except Exception as exc:
        rollback_errors = []
        for source_path in set(sources_dir.glob("*.jsonl")) - sources_before:
            try:
                source_path.unlink()
            except OSError as rollback_exc:
                rollback_errors.append(str(rollback_exc))
        try:
            _restore(snapshot)
        except OSError as rollback_exc:
            rollback_errors.append(str(rollback_exc))
        try:
            vector_ids_after = _vector_ids(preview.dataset_dir)
            _delete_vectors(preview.dataset_dir, vector_ids_after - vector_ids_before)
        except Exception as rollback_exc:
            rollback_errors.append(str(rollback_exc))
        if rollback_errors:
            raise RuntimeError(
                f"Context apply failed ({exc}); rollback also failed: {'; '.join(rollback_errors)}"
            ) from exc
        raise RuntimeError(f"Context apply failed and was rolled back: {exc}") from exc
