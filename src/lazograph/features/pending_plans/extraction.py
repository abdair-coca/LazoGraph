"""Conservative, deterministic extraction of plan lifecycles from source messages."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from lazograph.domain.identity import IdentityResolutionError, load_profiles
from lazograph.domain.plans import Plan, PlanValidationError
from lazograph.features.pending_plans.storage import dataset_timezone, rebuild_projection
from lazograph.features.pending_plans.kg_projection import rebuild_kg_projection


@dataclass(frozen=True)
class UnresolvedPlan:
    """Source-backed candidate deliberately withheld from the projection."""

    source_ids: tuple[str, ...]
    reason: str
    content: str


@dataclass(frozen=True)
class PlanExtraction:
    plans: tuple[Plan, ...]
    unresolved: tuple[UnresolvedPlan, ...]


_CANCEL = re.compile(r"\b(?:cancel(?:led|ed)?|call(?:ed)? off|cancelamos|cancelado|se cancela)\b", re.I)
_COMPLETE = re.compile(r"\b(?:completed|done|we did|finished|ya fuimos|terminamos|realizado)\b", re.I)
_RESCHEDULE = re.compile(r"\b(?:reschedul(?:e|ed|ing)|moved to|postponed|reprogram(?:amos|ado)|cambiamos(?:lo)? para)\b", re.I)
_PENDING = re.compile(r"\b(?:pending|pendiente|por hacer)\b", re.I)
_SCHEDULED = re.compile(r"\b(?:scheduled|agendado|programado)\b", re.I)
_PROPOSE = re.compile(r"\b(?:let'?s|we should|shall we|can we|plan(?:ning)? to|propose|vamos a|quedamos|te parece si|planeamos|propongo)\b", re.I)
_ACTIVITY = re.compile(r"\b(?:dinner|lunch|coffee|meet(?:ing)?|movie|trip|cena|almuerzo|cafe|caf[eé]|reuni[oó]n|viaje)\b", re.I)
_DAY_NAMES = {
    "monday": 0, "lunes": 0, "tuesday": 1, "martes": 1, "wednesday": 2,
    "miercoles": 2, "jueves": 3, "thursday": 3, "friday": 4, "viernes": 4,
    "saturday": 5, "sabado": 5, "sunday": 6, "domingo": 6,
}


def _key(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    return re.sub(r"\s+", " ", "".join(c for c in normalized if not unicodedata.combining(c))).strip()


def _timestamp(value: object, zone: ZoneInfo) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=zone) if parsed.tzinfo is None else parsed.astimezone(zone)


def _relative_date(text: str, when: datetime) -> datetime | None:
    normalized = _key(text)
    delta = 1 if re.search(r"\b(?:tomorrow|manana)\b", normalized) else 0
    if re.search(r"\b(?:next week|proxima semana|la semana que viene)\b", normalized):
        delta = 7
    for name, weekday in _DAY_NAMES.items():
        if re.search(rf"\b(?:next |este |proximo )?{name}\b", normalized):
            days = (weekday - when.weekday()) % 7 or 7
            delta = days + (7 if re.search(rf"\b(?:next |proximo ){name}\b", normalized) else 0)
            break
    if not delta and not re.search(r"\b(?:today|hoy)\b", normalized):
        return None
    date = (when + timedelta(days=delta)).date()
    return datetime(date.year, date.month, date.day, tzinfo=when.tzinfo)


def _participants(dataset_dir: Path, content: str, message: dict) -> tuple[str, ...] | None:
    try:
        profiles = load_profiles(dataset_dir)
    except IdentityResolutionError:
        return None
    owners: dict[str, set[str]] = {}
    persona: list[str] = []
    for profile in profiles:
        name = str(profile.get("name", "")).strip()
        if not name:
            continue
        if profile.get("identity_type") == "persona":
            persona.append(name)
        for alias in [name, *(profile.get("aliases", []) if isinstance(profile.get("aliases"), list) else [])]:
            alias_key = _key(str(alias))
            if alias_key:
                owners.setdefault(alias_key, set()).add(name)
    found: set[str] = set()
    for alias, names in owners.items():
        if re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", _key(content)):
            if len(names) != 1:
                return None
            found.update(names)
    sender = str(message.get("metadata", {}).get("sender", "")).strip() if isinstance(message.get("metadata"), dict) else ""
    if sender:
        sender_names = owners.get(_key(sender), set())
        if len(sender_names) == 1:
            found.update(sender_names)
    if re.search(r"\b(?:i|we|yo|nosotros|nosotras)\b", _key(content)) and len(persona) == 1:
        found.add(persona[0])
    return tuple(sorted(found, key=str.casefold)) or None


def _title(content: str) -> str | None:
    text = re.sub(r"\s+", " ", content).strip(" .!?")
    matched = re.search(r"(?:let'?s|we should|shall we|can we|plan(?:ning)? to|propose|vamos a|quedamos(?: para)?|te parece si|planeamos|propongo)\s+(.+)", text, re.I)
    value = matched.group(1) if matched else text
    value = re.split(r"\b(?:tomorrow|manana|next week|proxima semana|at|en)\b", value, maxsplit=1, flags=re.I)[0]
    value = re.split(r"\b(?:was moved to|is cancelled|was cancelled|is done|se cancela|se reprogram)\b", value, maxsplit=1, flags=re.I)[0]
    value = re.sub(r"^(?:a |the |have |ir a |hacer )", "", value, flags=re.I).strip(" ,.!?")
    value = re.sub(r"\s+(?:with|con)\s+[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ '\-]*$", "", value, flags=re.I).strip()
    return value if len(value) >= 3 and len(value) <= 90 else None


def _location(content: str) -> str | None:
    match = re.search(r"\b(?:at|en)\s+([A-Za-zÀ-ÿ0-9][A-Za-zÀ-ÿ0-9 '\-]{1,50}?)(?=\s+(?:tomorrow|mañana|manana|next|pr[oó]xim|on\s)|[,.!?]|$)", content, re.I)
    return match.group(1).strip() if match else None


def _matches(plan: Plan, title: str, participants: tuple[str, ...]) -> bool:
    return _key(plan.title) == _key(title) and set(plan.participants) == set(participants)


def _transition(plan: Plan, status: str, when: datetime, source_id: str, scheduled_for: datetime | None = None) -> Plan:
    if status == "scheduled" and plan.status == "scheduled":
        return plan.transition("pending", when, [source_id], confidence=.9).transition("scheduled", when, [source_id], confidence=.9, scheduled_for=scheduled_for)
    if plan.status == status:
        return plan
    return plan.transition(status, when, [source_id], confidence=.9, scheduled_for=scheduled_for)


def extract_plans(dataset_dir: Path) -> PlanExtraction:
    """Read normalized backups and return only unambiguous source-backed plan records."""
    zone = ZoneInfo(dataset_timezone(dataset_dir))
    records = []
    for source_path in sorted(dataset_dir.joinpath("sources").glob("*.jsonl")):
        for line_number, line in enumerate(source_path.read_text(encoding="utf-8").splitlines(), 1):
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            when = _timestamp(message.get("timestamp"), zone)
            content = str(message.get("content", "")).strip()
            if when and content:
                records.append((when, f"{source_path.name}:{line_number}", content, message))
    plans: list[Plan] = []
    unresolved: list[UnresolvedPlan] = []
    for when, source_id, content, message in sorted(records, key=lambda item: (item[0], item[1])):
        status = "cancelled" if _CANCEL.search(content) else "completed" if _COMPLETE.search(content) else "scheduled" if (_RESCHEDULE.search(content) or _SCHEDULED.search(content)) else "pending" if _PENDING.search(content) else "proposed"
        title = _title(content)
        participants = _participants(dataset_dir, content, message)
        dated = _relative_date(content, when)
        update = status in {"cancelled", "completed"} or _RESCHEDULE.search(content)
        if update:
            candidates = [plan for plan in plans if title and _key(plan.title) == _key(title)]
            if participants:
                exact = [plan for plan in candidates if set(participants) <= set(plan.participants)]
                candidates = exact or candidates
            if len(candidates) != 1:
                unresolved.append(UnresolvedPlan((source_id,), "ambiguous_lifecycle_match" if candidates else "no_lifecycle_match", content))
                continue
            plan = candidates[0]
            if plan.status in {"completed", "cancelled"}:
                unresolved.append(UnresolvedPlan((source_id,), "terminal_plan_update", content))
                continue
            target = "scheduled" if _RESCHEDULE.search(content) else status
            try:
                plans[plans.index(plan)] = _transition(plan, target, when, source_id, dated)
            except PlanValidationError:
                unresolved.append(UnresolvedPlan((source_id,), "invalid_lifecycle_transition", content))
            continue
        if not (_PROPOSE.search(content) or _PENDING.search(content) or _SCHEDULED.search(content) or (_ACTIVITY.search(content) and dated)):
            continue
        if not title or not participants:
            unresolved.append(UnresolvedPlan((source_id,), "ambiguous_plan_identity", content))
            continue
        duplicates = [plan for plan in plans if _matches(plan, title, participants)]
        if len(duplicates) == 1:
            continue
        try:
            plan = Plan.create(title, participants, when, [source_id], confidence=.8, location=_location(content))
            if status == "pending":
                plan = _transition(plan, "pending", when, source_id)
            elif status == "scheduled" or dated:
                plan = _transition(plan, "scheduled", when, source_id, dated)
            plans.append(plan)
        except PlanValidationError:
            unresolved.append(UnresolvedPlan((source_id,), "invalid_plan_candidate", content))
    return PlanExtraction(tuple(sorted(plans, key=lambda item: item.id)), tuple(unresolved))


def rebuild_extracted_projection(dataset_dir: Path) -> PlanExtraction:
    """Persist the complete deterministic projection while preserving source messages."""
    extraction = extract_plans(dataset_dir)
    rebuild_projection(dataset_dir, extraction.plans)
    rebuild_kg_projection(dataset_dir, extraction.plans)
    return extraction
