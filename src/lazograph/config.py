"""Runtime configuration shared by product commands."""

from __future__ import annotations

import os
import re
from pathlib import Path


class ConfigurationError(ValueError):
    """Runtime configuration is missing or ambiguous."""


def knowledge_root() -> Path:
    return Path(
        os.environ.get(
            "OPENPERSONA_KNOWLEDGE",
            Path.home() / ".openpersona" / "knowledge",
        )
    )


def resolve_dataset(slug: str | None, *, root: Path | None = None) -> Path:
    selected_root = root or knowledge_root()
    selected_slug = (slug or os.environ.get("LAZOGRAPH_SLUG", "")).strip()
    if selected_slug:
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", selected_slug):
            raise ConfigurationError(
                "Slug must use lowercase letters, numbers, hyphens, or underscores."
            )
        dataset = selected_root / selected_slug
        if not dataset.joinpath("dataset.json").exists():
            raise ConfigurationError(f"Dataset not found: {dataset}")
        return dataset

    candidates = sorted(
        path
        for path in selected_root.iterdir()
        if path.is_dir() and path.joinpath("dataset.json").exists()
    ) if selected_root.exists() else []
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise ConfigurationError(
            f"No datasets found under {selected_root}. Import a chat first."
        )
    names = ", ".join(path.name for path in candidates)
    raise ConfigurationError(
        f"Multiple datasets found ({names}). Pass --slug or set LAZOGRAPH_SLUG."
    )
