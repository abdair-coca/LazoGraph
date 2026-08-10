"""Safe, read-only preflight for Slice 1 chat imports."""

from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from adapters import detect_adapter
from scripts import ingest
from lazograph.config import knowledge_root


class ImportValidationError(ValueError):
    """Import cannot continue without changing user input."""


@dataclass(frozen=True)
class ParticipantPreview:
    name: str
    identity: str
    messages: int
    new_messages: int


@dataclass(frozen=True)
class ImportPreview:
    source: Path
    slug: str
    adapter: str
    persona: str
    participants: tuple[ParticipantPreview, ...]
    parsed_messages: int
    rejected_notices: int
    duplicates: int
    new_messages: int
    pii_flags: tuple[str, ...]
    equivalent_sources: tuple[dict, ...]
    dataset_dir: Path
    dataset_exists: bool
    same_source_reimport: bool


def _name_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    return re.sub(r"\s+", " ", normalized).strip().casefold()


def _sender(message: dict) -> str:
    metadata = message.get("metadata", {})
    if not isinstance(metadata, dict):
        return ""
    return str(metadata.get("sender", "")).strip()


def resolve_persona(participants: list[str], requested: str) -> str:
    """Resolve exact name first; allow only one unambiguous partial match."""
    requested_key = _name_key(requested)
    if not requested_key:
        raise ImportValidationError("Persona name cannot be empty.")

    exact = [name for name in participants if _name_key(name) == requested_key]
    if len(exact) == 1:
        return exact[0]

    partial = [name for name in participants if requested_key in _name_key(name)]
    if len(partial) == 1:
        return partial[0]
    if len(partial) > 1:
        names = ", ".join(sorted(partial, key=str.casefold))
        raise ImportValidationError(
            f'Persona "{requested}" is ambiguous. Matching participants: {names}'
        )

    names = ", ".join(sorted(participants, key=str.casefold)) or "none"
    raise ImportValidationError(
        f'Persona "{requested}" was not found. Participants: {names}'
    )


def _source_was_imported(dataset_dir: Path, source: Path) -> bool:
    index_path = dataset_dir / "sources" / ".source-index.json"
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return False

    expected = source.resolve()
    for entry in payload.get("files", []):
        stored = entry.get("source") if isinstance(entry, dict) else None
        if not stored:
            continue
        try:
            if Path(stored).resolve() == expected:
                return True
        except (OSError, RuntimeError):
            continue
    return False


def _count_rejected_notices(source: Path, adapter_name: str) -> int:
    if adapter_name != "chat_export" or source.suffix.casefold() != ".txt":
        return 0
    from adapters.chat_export import count_whatsapp_rejected_notices

    return count_whatsapp_rejected_notices(source)


def build_preview(
    source_path: str | Path,
    *,
    slug: str,
    persona: str,
    adapter_name: str | None = None,
    since: str | None = None,
    root: Path | None = None,
) -> ImportPreview:
    """Parse and validate every write boundary without mutating the dataset."""
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", slug):
        raise ImportValidationError(
            "Slug must use lowercase letters, numbers, hyphens, or underscores."
        )

    source = Path(source_path).expanduser()
    if not source.exists():
        raise ImportValidationError(f"Source not found: {source}")

    selected_adapter = adapter_name or detect_adapter(str(source))
    if not selected_adapter:
        raise ImportValidationError(
            "Cannot detect source adapter. Pass --adapter explicitly."
        )

    try:
        adapter = ingest._load_adapter(selected_adapter)
        messages = adapter.parse(
            str(source),
            persona_name="",
            persona_exact=True,
            since=since,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ImportValidationError(str(exc)) from exc

    messages, rejected_after_parse = ingest._reject_invalid_chat_senders(messages)
    if not messages:
        raise ImportValidationError("No human messages parsed from source.")

    counts = Counter(_sender(message) for message in messages if _sender(message))
    if not counts:
        raise ImportValidationError(
            "No participant senders found. Slice 1 requires identifiable chat senders."
        )
    canonical_persona = resolve_persona(list(counts), persona)

    persona_key = _name_key(canonical_persona)
    for message in messages:
        message["role"] = (
            "assistant" if _name_key(_sender(message)) == persona_key else "user"
        )

    dataset_dir = (root or knowledge_root()) / slug
    existing_hashes = ingest._load_existing_hashes(dataset_dir)
    new_messages, duplicate_count = ingest.dedup_messages(messages, existing_hashes)
    new_counts = Counter(_sender(message) for message in new_messages if _sender(message))
    equivalent = ingest._find_equivalent_sources(dataset_dir, messages)
    pii_flags = ingest.scan_pii(messages)

    participants = tuple(
        ParticipantPreview(
            name=name,
            identity="persona" if _name_key(name) == persona_key else "contact",
            messages=count,
            new_messages=new_counts.get(name, 0),
        )
        for name, count in sorted(counts.items(), key=lambda item: item[0].casefold())
    )

    return ImportPreview(
        source=source.resolve(),
        slug=slug,
        adapter=selected_adapter,
        persona=canonical_persona,
        participants=participants,
        parsed_messages=len(messages),
        rejected_notices=(
            _count_rejected_notices(source, selected_adapter) + rejected_after_parse
        ),
        duplicates=duplicate_count,
        new_messages=len(new_messages),
        pii_flags=tuple(sorted(pii_flags)),
        equivalent_sources=tuple(equivalent),
        dataset_dir=dataset_dir,
        dataset_exists=dataset_dir.exists(),
        same_source_reimport=(
            not new_messages and _source_was_imported(dataset_dir, source)
        ),
    )
