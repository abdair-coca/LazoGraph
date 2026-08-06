#!/usr/bin/env python3
"""Recoverable, selective quarantine for active source backups."""

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


def quarantine_sources(
    dataset_dir: Path,
    filenames: list[str],
    *,
    kept: str | None = None,
    reason: str,
    replacement_source: str | None = None,
) -> dict:
    """Move exact active JSONL files into a timestamped recoverable quarantine."""
    names = sorted(set(filenames))
    if not names:
        raise RuntimeError('No source files selected for quarantine')
    if any(Path(name).name != name for name in names):
        raise RuntimeError('Quarantine selections must be filenames, not paths')

    sources_dir = dataset_dir / 'sources'
    paths = [sources_dir / name for name in names]
    missing = [path.name for path in paths if not path.exists() or path.suffix.casefold() != '.jsonl']
    if missing:
        raise RuntimeError(f'Active JSONL source not found: {", ".join(missing)}')

    timestamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    quarantine_dir = sources_dir / 'quarantine' / timestamp
    counter = 1
    while quarantine_dir.exists():
        quarantine_dir = sources_dir / 'quarantine' / f'{timestamp}-{counter}'
        counter += 1
    quarantine_dir.mkdir(parents=True)

    index_path = sources_dir / '.source-index.json'
    if index_path.exists():
        shutil.copy2(index_path, quarantine_dir / f'source-index-{timestamp}.json')

    moved = []
    for source_path in paths:
        source_path.replace(quarantine_dir / source_path.name)
        moved.append(source_path.name)

    _update_source_index(index_path, moved, quarantine_dir)
    manifest = {
        'applied_at': datetime.now(timezone.utc).isoformat(),
        'reason': reason,
        'kept': kept,
        'quarantined': moved,
        'replacement_source': replacement_source,
    }
    (quarantine_dir / 'reconciliation.json').write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + '\n',
        encoding='utf-8',
    )
    return {
        'quarantined': moved,
        'quarantine_dir': str(quarantine_dir),
        'manifest': manifest,
    }


def _update_source_index(index_path: Path, moved: list[str], quarantine_dir: Path):
    if not index_path.exists():
        return
    try:
        index = json.loads(index_path.read_text(encoding='utf-8'))
    except (json.JSONDecodeError, OSError):
        return
    moved_set = set(moved)
    index['files'] = [
        entry for entry in index.get('files', [])
        if entry.get('filename') not in moved_set
    ]
    index.setdefault('quarantine_history', []).append({
        'at': datetime.now(timezone.utc).isoformat(),
        'files': moved,
        'location': str(quarantine_dir),
    })
    index['last_updated'] = datetime.now(timezone.utc).isoformat()
    index_path.write_text(
        json.dumps(index, indent=2, ensure_ascii=False) + '\n',
        encoding='utf-8',
    )
