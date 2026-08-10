"""Canonical participant identity resolution."""

from __future__ import annotations

import json
from pathlib import Path


class IdentityResolutionError(ValueError):
    """Participant identity cannot be resolved safely."""


def load_profiles(dataset_dir: Path) -> list[dict]:
    try:
        payload = json.loads(
            dataset_dir.joinpath("participants.json").read_text(encoding="utf-8")
        )
    except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
        raise IdentityResolutionError(
            "participants.json is missing or invalid; rebuild identities first."
        ) from exc
    profiles = payload.get("participants", [])
    if not isinstance(profiles, list) or not profiles:
        raise IdentityResolutionError("Dataset has no participant profiles.")
    return [profile for profile in profiles if isinstance(profile, dict)]


def resolve_participant(dataset_dir: Path, query: str) -> dict:
    normalized = query.casefold().strip()
    if not normalized:
        raise IdentityResolutionError("Participant name cannot be empty.")
    profiles = load_profiles(dataset_dir)

    exact = []
    for profile in profiles:
        name = str(profile.get("name", "")).strip()
        raw_aliases = profile.get("aliases", [])
        aliases = [name, *(raw_aliases if isinstance(raw_aliases, list) else [])]
        if any(str(alias).casefold().strip() == normalized for alias in aliases):
            exact.append(profile)
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise IdentityResolutionError(f'Participant "{query}" is ambiguous.')

    partial = [
        profile
        for profile in profiles
        if normalized in str(profile.get("name", "")).casefold()
        or str(profile.get("name", "")).casefold() in normalized
    ]
    if len(partial) == 1:
        return partial[0]
    if len(partial) > 1:
        names = ", ".join(str(item.get("name", "")) for item in partial)
        raise IdentityResolutionError(
            f'Participant "{query}" is ambiguous. Matches: {names}'
        )
    names = ", ".join(str(item.get("name", "")) for item in profiles)
    raise IdentityResolutionError(
        f'No participant matching "{query}". Available: {names}'
    )
