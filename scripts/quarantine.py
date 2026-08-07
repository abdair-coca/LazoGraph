#!/usr/bin/env python3
"""Inspect and transactionally restore quarantined source backups."""

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import ingest
import rebuild_all
from dataset_invariants import validate_dataset


def knowledge_root() -> Path:
    return Path(os.environ.get(
        'OPENPERSONA_KNOWLEDGE',
        Path.home() / '.openpersona' / 'knowledge',
    )).expanduser().resolve()


def _read_json(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return value if isinstance(value, dict) else None


def _batch_dir(dataset_dir: Path, batch: str) -> Path:
    if not batch or Path(batch).name != batch or batch in {'.', '..'}:
        raise RuntimeError('Batch must be one quarantine directory name')
    root = (dataset_dir / 'sources' / 'quarantine').resolve()
    path = (root / batch).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise RuntimeError('Quarantine batch escapes dataset') from exc
    if not path.is_dir():
        raise RuntimeError(f'Quarantine batch not found: {batch}')
    return path


def inspect_batch(dataset_dir: Path, batch: str) -> dict:
    path = _batch_dir(dataset_dir, batch)
    manifest = _read_json(path / 'reconciliation.json') or {}
    restoration = _read_json(path / 'restoration.json')
    files = []
    for source in sorted(path.glob('*.jsonl')):
        with source.open(encoding='utf-8') as stream:
            lines = sum(1 for line in stream if line.strip())
        files.append({
            'filename': source.name,
            'lines': lines,
            'bytes': source.stat().st_size,
            'sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
        })
    return {
        'batch': path.name,
        'path': str(path),
        'status': 'restored' if restoration else 'available',
        'reason': manifest.get('reason', 'unknown'),
        'applied_at': manifest.get('applied_at'),
        'kept': manifest.get('kept'),
        'replacement_source': manifest.get('replacement_source'),
        'manifest_files': manifest.get('quarantined', []),
        'files': files,
        'restoration': restoration,
    }


def list_batches(dataset_dir: Path) -> list[dict]:
    root = dataset_dir / 'sources' / 'quarantine'
    if not root.exists():
        return []
    return [inspect_batch(dataset_dir, path.name) for path in sorted(root.iterdir()) if path.is_dir()]


def _restore_index_entries(dataset_dir: Path, batch_dir: Path, filenames: list[str]) -> None:
    sources_dir = dataset_dir / 'sources'
    index_path = sources_dir / '.source-index.json'
    current = _read_json(index_path) or {'files': []}
    backups = sorted(batch_dir.glob('source-index-*.json'))
    previous = _read_json(backups[-1]) if backups else None
    previous_entries = {
        entry.get('filename'): entry
        for entry in (previous or {}).get('files', [])
        if isinstance(entry, dict)
    }
    existing = {
        entry.get('filename')
        for entry in current.get('files', [])
        if isinstance(entry, dict)
    }
    for filename in filenames:
        if filename in existing:
            continue
        entry = previous_entries.get(filename)
        if entry is None:
            path = sources_dir / filename
            messages = [
                json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()
                if line.strip()
            ]
            entry = {
                'filename': filename,
                'adapter': 'restored',
                'source': 'quarantine-restore',
                'imported_at': datetime.now(timezone.utc).isoformat(),
                'lines': len(messages),
                'assistant_turns': sum(item.get('role') == 'assistant' for item in messages),
                'pii_flags': None,
            }
        current.setdefault('files', []).append(entry)
    current.setdefault('restore_history', []).append({
        'at': datetime.now(timezone.utc).isoformat(),
        'batch': batch_dir.name,
        'files': filenames,
    })
    current['last_updated'] = datetime.now(timezone.utc).isoformat()
    index_path.write_text(
        json.dumps(current, indent=2, ensure_ascii=False) + '\n',
        encoding='utf-8',
    )


def _rebuild_derived_layers(dataset_dir: Path, slug: str) -> dict:
    messages = ingest._load_stored_messages(dataset_dir)
    removed = ingest._prune_mempalace(dataset_dir, slug, messages)
    stored = ingest._store_in_mempalace(dataset_dir, slug, messages, show_progress=True)
    cleared = ingest._clear_managed_kg(dataset_dir)
    pruned = ingest._prune_invalid_kg_entities(dataset_dir)
    kg_stats = ingest._extract_kg_triples(dataset_dir, messages)
    ingest._write_participant_profiles(dataset_dir, messages)
    ingest._replace_stats(dataset_dir, messages, kg_stats)
    invariants = validate_dataset(dataset_dir)
    if not invariants['ok']:
        raise RuntimeError(f'Restored dataset invariant failure: {invariants["errors"]}')
    return {
        'messages': len(messages),
        'vectors_stored': stored,
        'vectors_pruned': removed,
        'relationships_cleared': cleared,
        'entities_pruned': pruned,
        'kg': kg_stats,
        'invariants': invariants,
    }


def restore_batch(dataset_dir: Path, batch: str, *, apply: bool = False) -> dict:
    """Restore one batch; rollback sources and derived layers if rebuilding fails."""
    batch_dir = _batch_dir(dataset_dir, batch)
    if (batch_dir / 'restoration.json').exists():
        raise RuntimeError(f'Quarantine batch already restored: {batch}')
    files = sorted(batch_dir.glob('*.jsonl'))
    if not files:
        raise RuntimeError(f'Quarantine batch has no restorable JSONL files: {batch}')
    sources_dir = dataset_dir / 'sources'
    conflicts = [path.name for path in files if (sources_dir / path.name).exists()]
    if conflicts:
        raise RuntimeError(f'Active source conflicts with restore: {", ".join(conflicts)}')
    plan = {
        'batch': batch,
        'files': [path.name for path in files],
        'apply': apply,
        'rebuilds': ['vectors', 'participant-profiles', 'knowledge-graph', 'dataset-stats'],
    }
    if not apply:
        return plan

    index_path = sources_dir / '.source-index.json'
    with rebuild_all._dataset_lock(dataset_dir):
        with tempfile.TemporaryDirectory(prefix='LazoGraph-restore-') as temp:
            backup_dir = Path(temp) / 'derived'
            manifest = rebuild_all._snapshot_state(dataset_dir, backup_dir)
            index_backup = Path(temp) / 'source-index.json'
            index_existed = index_path.exists()
            if index_existed:
                shutil.copy2(index_path, index_backup)
            moved = []
            try:
                for source in files:
                    source.replace(sources_dir / source.name)
                    moved.append(source.name)
                _restore_index_entries(dataset_dir, batch_dir, moved)
                rebuild = _rebuild_derived_layers(dataset_dir, dataset_dir.name)
            except BaseException:
                rebuild_all._restore_state(dataset_dir, backup_dir, manifest)
                if index_existed:
                    shutil.copy2(index_backup, index_path)
                else:
                    index_path.unlink(missing_ok=True)
                for filename in moved:
                    active = sources_dir / filename
                    if active.exists():
                        active.replace(batch_dir / filename)
                raise

    restoration = {
        'restored_at': datetime.now(timezone.utc).isoformat(),
        'files': moved,
        'rebuild': rebuild,
    }
    (batch_dir / 'restoration.json').write_text(
        json.dumps(restoration, indent=2, ensure_ascii=False) + '\n',
        encoding='utf-8',
    )
    return {**plan, 'restoration': restoration}


def _print_batch(report: dict) -> None:
    print(f'Batch: {report["batch"]} [{report["status"]}]')
    print(f'  Reason: {report["reason"]}')
    print(f'  Applied: {report["applied_at"] or "unknown"}')
    print(f'  Files available: {len(report["files"])}')
    for item in report['files']:
        print(f'    - {item["filename"]}: {item["lines"]} lines, sha256:{item["sha256"][:16]}')


def main() -> None:
    parser = argparse.ArgumentParser(description='Inspect or restore source quarantine')
    parser.add_argument('--slug', required=True, help='Persona dataset slug')
    parser.add_argument('--json', action='store_true', help='Output machine-readable JSON')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('list', help='List all quarantine batches')
    show = commands.add_parser('show', help='Inspect one quarantine batch')
    show.add_argument('batch')
    restore = commands.add_parser('restore', help='Plan or apply transactional restoration')
    restore.add_argument('batch')
    restore.add_argument('--apply', action='store_true', help='Restore and rebuild affected layers')
    args = parser.parse_args()

    dataset_dir = knowledge_root() / args.slug
    if not dataset_dir.exists():
        print(f'Dataset not found: {dataset_dir}', file=sys.stderr)
        raise SystemExit(1)
    try:
        if args.command == 'list':
            result = list_batches(dataset_dir)
        elif args.command == 'show':
            result = inspect_batch(dataset_dir, args.batch)
        else:
            result = restore_batch(dataset_dir, args.batch, apply=args.apply)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.command == 'list':
        print(f'Quarantine batches: {len(result)}')
        for item in result:
            print(f'  - {item["batch"]}: {item["status"]}, {len(item["files"])} files, {item["reason"]}')
    elif args.command == 'show':
        _print_batch(result)
    else:
        print(f'Restore {"applied" if args.apply else "plan"}: {result["batch"]}')
        print(f'  Files: {", ".join(result["files"])}')
        print(f'  Derived layers: {", ".join(result["rebuilds"])}')
        if not args.apply:
            print('  Dry run only. Add --apply to restore transactionally.')


if __name__ == '__main__':
    main()
