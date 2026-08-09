"""Append-only correction ledger and effective graph projection."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator

from lazograph.domain.correction import CorrectionPreview, SYMMETRIC_RELATIONS


class CorrectionLedgerError(RuntimeError):
    """Correction history is unavailable, corrupt, locked, or inconsistent."""


Clock = Callable[[], datetime]
IdFactory = Callable[[], str]


def ledger_path(dataset_dir: Path) -> Path:
    return dataset_dir / "corrections" / "ledger.jsonl"


def load_events(dataset_dir: Path) -> list[dict]:
    path = ledger_path(dataset_dir)
    if not path.exists():
        return []
    events = []
    try:
        with path.open(encoding="utf-8") as source:
            for line_number, line in enumerate(source, 1):
                if not line.strip():
                    continue
                event = json.loads(line)
                if not isinstance(event, dict) or event.get("event_type") not in {
                    "correction", "undo"
                }:
                    raise ValueError("unsupported event")
                if not event.get("event_id") or not event.get("created_at"):
                    raise ValueError("missing event identity")
                events.append(event)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise CorrectionLedgerError(
            f"Correction ledger is invalid at {path}:{line_number if 'line_number' in locals() else 0}."
        ) from exc
    return events


def correction_records(dataset_dir: Path) -> list[dict]:
    events = load_events(dataset_dir)
    corrections = [dict(event) for event in events if event["event_type"] == "correction"]
    undone_by: dict[str, str] = {}
    known = {event.get("claim_id") for event in corrections}
    for event in events:
        if event["event_type"] != "undo":
            continue
        target = event.get("target_claim_id")
        if target not in known:
            raise CorrectionLedgerError(
                f'Undo event {event["event_id"]} references unknown claim {target}.'
            )
        undone_by[str(target)] = str(event["event_id"])
    for record in corrections:
        undo_id = undone_by.get(str(record.get("claim_id")))
        record["status"] = "undone" if undo_id else "active"
        record["undo_event_id"] = undo_id
    return corrections


def active_corrections(dataset_dir: Path) -> list[dict]:
    return [record for record in correction_records(dataset_dir) if record["status"] == "active"]


def find_active_by_fingerprint(dataset_dir: Path, fingerprint: str) -> dict | None:
    return next(
        (
            record for record in reversed(active_corrections(dataset_dir))
            if record.get("fingerprint") == fingerprint
        ),
        None,
    )


@contextmanager
def _ledger_lock(dataset_dir: Path) -> Iterator[None]:
    directory = dataset_dir / "corrections"
    directory.mkdir(parents=True, exist_ok=True)
    lock = directory / ".ledger.lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except (FileExistsError, PermissionError) as exc:
        if lock.exists():
            raise CorrectionLedgerError(
                f"Correction ledger is locked by another operation: {lock}"
            ) from exc
        raise
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as target:
            target.write(str(os.getpid()))
        yield
    finally:
        lock.unlink(missing_ok=True)


def _append_event(dataset_dir: Path, event: dict) -> None:
    path = ledger_path(dataset_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n"
    try:
        with path.open("a", encoding="utf-8", newline="") as target:
            target.write(serialized)
            target.flush()
            os.fsync(target.fileno())
    except OSError as exc:
        raise CorrectionLedgerError(f"Could not append correction ledger: {exc}") from exc


def _new_id(prefix: str, id_factory: IdFactory) -> str:
    raw = id_factory().strip().replace("-", "")
    if not raw:
        raw = uuid.uuid4().hex
    return f"{prefix}-{raw[:16]}"


def append_correction(
    dataset_dir: Path,
    preview: CorrectionPreview,
    *,
    clock: Clock | None = None,
    id_factory: IdFactory | None = None,
) -> dict:
    clock = clock or (lambda: datetime.now(timezone.utc))
    id_factory = id_factory or (lambda: uuid.uuid4().hex)
    with _ledger_lock(dataset_dir):
        existing = find_active_by_fingerprint(dataset_dir, preview.fingerprint)
        if existing:
            return {"appended": False, "record": existing}
        if not preview.matched_claims:
            raise CorrectionLedgerError("Correction has no matched effective claim to retract.")
        claim_id = _new_id("claim", id_factory)
        created_at = clock().astimezone(timezone.utc).isoformat()
        retract = {
            **preview.retract.to_dict(),
            "claim_id": f"{claim_id}:retract",
        }
        assert_claim = {
            **preview.assert_claim.to_dict(),
            "claim_id": f"{claim_id}:assert",
        }
        event = {
            "schema_version": 1,
            "event_type": "correction",
            "event_id": claim_id,
            "claim_id": claim_id,
            "created_at": created_at,
            "fingerprint": preview.fingerprint,
            "raw_text": preview.raw_text,
            "authority": "user",
            "authored_by": "dataset_owner",
            "retract": retract,
            "assert": assert_claim,
            "matched_claim_ids": [claim.claim_id for claim in preview.matched_claims],
        }
        _append_event(dataset_dir, event)
        return {"appended": True, "record": {**event, "status": "active", "undo_event_id": None}}


def undo_correction(
    dataset_dir: Path,
    target_claim_id: str,
    *,
    clock: Clock | None = None,
    id_factory: IdFactory | None = None,
) -> dict:
    clock = clock or (lambda: datetime.now(timezone.utc))
    id_factory = id_factory or (lambda: uuid.uuid4().hex)
    with _ledger_lock(dataset_dir):
        records = correction_records(dataset_dir)
        matches = [
            record for record in records
            if target_claim_id in {
                record.get("claim_id"),
                record.get("retract", {}).get("claim_id"),
                record.get("assert", {}).get("claim_id"),
            }
        ]
        if not matches:
            raise CorrectionLedgerError(f'No correction claim matching "{target_claim_id}".')
        if len(matches) > 1:
            raise CorrectionLedgerError(f'Correction claim "{target_claim_id}" is ambiguous.')
        record = matches[0]
        if record["status"] == "undone":
            return {"appended": False, "record": record, "event": None}
        event = {
            "schema_version": 1,
            "event_type": "undo",
            "event_id": _new_id("undo", id_factory),
            "target_claim_id": record["claim_id"],
            "created_at": clock().astimezone(timezone.utc).isoformat(),
            "authority": "user",
            "authored_by": "dataset_owner",
        }
        _append_event(dataset_dir, event)
        return {"appended": True, "record": {**record, "status": "undone"}, "event": event}


def _claim_matches(relationship: dict, claim: dict) -> bool:
    predicate = str(claim.get("predicate", ""))
    if str(relationship.get("type", "")).casefold() != predicate.casefold():
        return False
    left = str(relationship.get("from", "")).casefold().strip()
    right = str(relationship.get("to", "")).casefold().strip()
    subject = str(claim.get("subject", "")).casefold().strip()
    object_name = str(claim.get("object", "")).casefold().strip()
    if predicate in SYMMETRIC_RELATIONS:
        return {left, right} == {subject, object_name}
    return left == subject and right == object_name


def project_effective_graph(
    dataset_dir: Path,
    entities: set[str],
    relationships: list[dict],
) -> tuple[set[str], list[dict], dict]:
    """Overlay active corrections without mutating the generated graph."""
    effective_entities = set(entities)
    effective = [dict(relationship) for relationship in relationships]
    applied = 0
    retracted = 0
    records = correction_records(dataset_dir)
    active_records = [record for record in records if record["status"] == "active"]
    for record in active_records:
        before = len(effective)
        effective = [
            relationship for relationship in effective
            if not _claim_matches(relationship, record["retract"])
        ]
        retracted += before - len(effective)
        effective = [
            relationship for relationship in effective
            if not _claim_matches(relationship, record["assert"])
        ]
        assertion = record["assert"]
        effective.append({
            "from": assertion["subject"],
            "to": assertion["object"],
            "type": assertion["predicate"],
            "confidence": 1.0,
            "source": f'correction:{record["claim_id"]}',
            "timestamp": record["created_at"],
            "claim_id": assertion["claim_id"],
            "correction_id": record["claim_id"],
            "provenance": "user_correction",
            "authority": "user",
            "authored_by": "dataset_owner",
        })
        effective_entities.update((assertion["subject"], assertion["object"]))
        applied += 1
    return effective_entities, effective, {
        "correction_records": len(records),
        "active_corrections": applied,
        "retracted_relationships": retracted,
    }
