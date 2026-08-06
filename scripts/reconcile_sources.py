#!/usr/bin/env python3
"""Quarantine duplicate source backups and reconcile private dataset counters."""

import argparse
import json
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import ingest
from dataset_invariants import print_report as print_invariant_report
from dataset_invariants import validate_dataset
from source_reconciliation import quarantine_sources

KNOWLEDGE_ROOT = Path(os.environ.get(
    'OPENPERSONA_KNOWLEDGE',
    Path.home() / '.openpersona' / 'knowledge',
))


def main():
    parser = argparse.ArgumentParser(
        description='Keep one authoritative source and quarantine other JSONL backups'
    )
    parser.add_argument('--slug', required=True, help='Persona dataset slug')
    parser.add_argument('--keep', required=True, help='Authoritative JSONL filename')
    parser.add_argument('--apply', action='store_true', help='Apply recoverable quarantine')
    args = parser.parse_args()

    dataset_dir = KNOWLEDGE_ROOT / args.slug
    if not dataset_dir.exists():
        print(f'Dataset not found: {dataset_dir}', file=sys.stderr)
        sys.exit(1)
    if Path(args.keep).name != args.keep:
        parser.error('--keep must be a filename, not a path')

    result = reconcile_sources(dataset_dir, args.keep, apply=args.apply)
    print(f'Authoritative: {result["kept"]}')
    print(f'Quarantine candidates: {len(result["quarantined"])}')
    for filename in result['quarantined']:
        print(f'  - {filename}')
    print(f'Unique messages after reconciliation: {result["messages"]}')
    if args.apply:
        if result['quarantine_dir']:
            print(f'Quarantine: {result["quarantine_dir"]}')
            print('Reconciliation applied. Next: rebuild KG, then vectors.')
        else:
            print('Nothing to quarantine.')
        print_invariant_report(result['invariants'], strict=False)
    else:
        print('Dry run only. Add --apply to move duplicate backups.')


def reconcile_sources(dataset_dir: Path, keep: str, *, apply: bool = False) -> dict:
    sources_dir = dataset_dir / 'sources'
    keep_path = sources_dir / keep
    if not keep_path.exists() or keep_path.suffix.casefold() != '.jsonl':
        raise RuntimeError(f'Authoritative JSONL not found: {keep_path}')

    candidates = sorted(
        path for path in sources_dir.glob('*.jsonl') if path.name != keep
    )
    if not apply:
        messages = _load_unique_from_files([keep_path])
        return {
            'kept': keep,
            'quarantined': [path.name for path in candidates],
            'messages': len(messages),
            'quarantine_dir': None,
        }

    if not candidates:
        messages = ingest._load_stored_messages(dataset_dir)
        ingest._write_participant_profiles(dataset_dir, messages)
        _reconcile_dataset_stats(dataset_dir, messages)
        return {
            'kept': keep,
            'quarantined': [],
            'messages': len(messages),
            'quarantine_dir': None,
            'invariants': validate_dataset(dataset_dir),
        }

    quarantine = quarantine_sources(
        dataset_dir,
        [path.name for path in candidates],
        kept=keep,
        reason='manual-source-reconciliation',
    )
    quarantine_dir = Path(quarantine['quarantine_dir'])
    moved = quarantine['quarantined']
    messages = ingest._load_stored_messages(dataset_dir)
    ingest._write_participant_profiles(dataset_dir, messages)
    _reconcile_dataset_stats(dataset_dir, messages)
    invariants = validate_dataset(dataset_dir)
    return {
        'kept': keep,
        'quarantined': moved,
        'messages': len(messages),
        'quarantine_dir': str(quarantine_dir),
        'invariants': invariants,
    }


def _load_unique_from_files(paths: list[Path]) -> list[dict]:
    messages = []
    seen = set()
    for path in paths:
        with path.open(encoding='utf-8') as source:
            for line in source:
                try:
                    message = json.loads(line)
                    key = ingest._content_hash(message)
                except (json.JSONDecodeError, KeyError):
                    continue
                if key not in seen:
                    seen.add(key)
                    messages.append(message)
    return messages


def _reconcile_dataset_stats(dataset_dir: Path, messages: list[dict]):
    metadata_path = dataset_dir / 'dataset.json'
    metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
    stats = metadata.setdefault('stats', {})
    stats['sources'] = len(list((dataset_dir / 'sources').glob('*.jsonl')))
    stats['total_messages'] = len(messages)
    stats['assistant_turns'] = sum(message.get('role') == 'assistant' for message in messages)
    metadata_path.write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + '\n',
        encoding='utf-8',
    )


if __name__ == '__main__':
    main()
