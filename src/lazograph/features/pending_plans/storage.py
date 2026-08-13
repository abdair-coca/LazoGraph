"""Derived plan projection persistence; source records remain immutable."""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Iterable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from lazograph.domain.plans import Plan, PlanValidationError


class PlanProjectionError(RuntimeError):
    """Plan projection is unavailable, corrupt, or locked."""


def projection_path(dataset_dir: Path) -> Path:
    return dataset_dir / "plans" / "projection.json"


def dataset_timezone(dataset_dir: Path) -> str:
    try:
        metadata = json.loads(dataset_dir.joinpath("dataset.json").read_text(encoding="utf-8"))
        value = metadata["timezone"]
        if not isinstance(value, str) or not value.strip():
            raise ValueError("missing timezone")
        return ZoneInfo(value).key
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError, ZoneInfoNotFoundError) as exc:
        raise PlanProjectionError("dataset.json must declare a valid IANA timezone before plans can be derived.") from exc


def load_projection(dataset_dir: Path) -> list[Plan]:
    path = projection_path(dataset_dir)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != 1 or payload.get("dataset_timezone") != dataset_timezone(dataset_dir):
            raise ValueError("unsupported projection")
        plans = [Plan.from_dict(item) for item in payload["plans"]]
        if [plan.id for plan in plans] != sorted(plan.id for plan in plans) or len({plan.id for plan in plans}) != len(plans):
            raise ValueError("non-deterministic plan order")
        return plans
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError, PlanValidationError) as exc:
        raise PlanProjectionError(f"Plan projection is missing or corrupt: {path}") from exc


@contextmanager
def _projection_lock(dataset_dir: Path) -> Iterator[None]:
    directory = projection_path(dataset_dir).parent
    directory.mkdir(parents=True, exist_ok=True)
    lock = directory / ".projection.lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except (FileExistsError, PermissionError) as exc:
        raise PlanProjectionError(f"Plan projection is locked: {lock}") from exc
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as target:
            target.write(str(os.getpid()))
        yield
    finally:
        lock.unlink(missing_ok=True)


def rebuild_projection(dataset_dir: Path, plans: Iterable[Plan]) -> list[Plan]:
    """Atomically replace the complete derived projection from immutable source evidence."""
    timezone = dataset_timezone(dataset_dir)
    ordered = sorted(plans, key=lambda plan: plan.id)
    if len({plan.id for plan in ordered}) != len(ordered):
        raise PlanProjectionError("Plan projection cannot contain duplicate plan IDs.")
    payload = {"schema_version": 1, "dataset_timezone": timezone, "plans": [plan.to_dict() for plan in ordered]}
    path = projection_path(dataset_dir)
    with _projection_lock(dataset_dir):
        descriptor, temporary = tempfile.mkstemp(prefix=".projection-", suffix=".json", dir=path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as target:
                json.dump(payload, target, ensure_ascii=False, sort_keys=True, indent=2)
                target.write("\n")
                target.flush()
                os.fsync(target.fileno())
            os.replace(temporary, path)
        except OSError as exc:
            raise PlanProjectionError(f"Could not atomically replace plan projection: {exc}") from exc
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return ordered
