#!/usr/bin/env python3
"""Cross-layer consistency checks for a persona knowledge dataset."""

import hashlib
import json
import sqlite3
from pathlib import Path


SOURCE_SUFFIXES = {'.jsonl', '.txt', '.json', '.csv'}
_AUTO_VECTOR_COUNT = object()


def _message_hash(message: dict) -> str:
    key = f'{message["role"]}:{message["content"]}'
    return hashlib.sha256(key.encode('utf-8')).hexdigest()[:16]


def load_unique_messages(dataset_dir: Path) -> list[dict]:
    """Load unique normalized messages from active JSONL backups."""
    messages = []
    seen = set()
    for source_path in sorted((dataset_dir / 'sources').glob('*.jsonl')):
        with source_path.open(encoding='utf-8') as source:
            for line in source:
                try:
                    message = json.loads(line)
                    fingerprint = _message_hash(message)
                except (json.JSONDecodeError, KeyError, TypeError):
                    continue
                if fingerprint in seen:
                    continue
                seen.add(fingerprint)
                messages.append(message)
    return messages


def build_source_snapshot(dataset_dir: Path) -> dict[str, str]:
    """Hash every active exportable source file."""
    sources_dir = dataset_dir / 'sources'
    if not sources_dir.exists():
        return {}
    return {
        path.name: 'sha256:' + hashlib.sha256(path.read_bytes()).hexdigest()[:16]
        for path in sorted(sources_dir.iterdir())
        if not path.name.startswith('.') and path.suffix in SOURCE_SUFFIXES
    }


def _read_json(path: Path) -> dict | None:
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return payload if isinstance(payload, dict) else None


def _read_vector_count(dataset_dir: Path) -> int | None:
    chroma_path = dataset_dir / '.mempalace' / 'palace' / 'chroma.sqlite3'
    if not chroma_path.exists():
        return None
    try:
        connection = sqlite3.connect(chroma_path)
        try:
            row = connection.execute('SELECT COUNT(*) FROM embeddings').fetchone()
        finally:
            connection.close()
    except sqlite3.Error:
        return None
    return int(row[0]) if row else 0


def validate_dataset(
    dataset_dir: Path,
    *,
    vector_count: int | None | object = _AUTO_VECTOR_COUNT,
    export_dir: Path | None = None,
) -> dict:
    """Return deterministic cross-layer invariant results without changing data."""
    messages = load_unique_messages(dataset_dir)
    source_files = sorted((dataset_dir / 'sources').glob('*.jsonl'))
    expected_messages = len(messages)
    expected_assistant = sum(message.get('role') == 'assistant' for message in messages)
    expected_participant_messages = sum(
        bool(str(message.get('metadata', {}).get('sender', '')).strip())
        for message in messages
        if isinstance(message.get('metadata', {}), dict)
    )
    errors = []
    warnings = []

    def check(name: str, expected, actual):
        if actual != expected:
            errors.append({'check': name, 'expected': expected, 'actual': actual})

    dataset_meta = _read_json(dataset_dir / 'dataset.json')
    if dataset_meta is None:
        errors.append({'check': 'dataset.metadata', 'expected': 'valid JSON', 'actual': 'missing/invalid'})
        stats = {}
    else:
        stats = dataset_meta.get('stats', {})
        check('stats.sources', len(source_files), stats.get('sources'))
        check('stats.total_messages', expected_messages, stats.get('total_messages'))
        check('stats.assistant_turns', expected_assistant, stats.get('assistant_turns'))

    participant_payload = _read_json(dataset_dir / 'participants.json')
    if participant_payload is None:
        if expected_participant_messages:
            errors.append({
                'check': 'participants.message_count',
                'expected': expected_participant_messages,
                'actual': 'missing/invalid',
            })
        participant_total = 0
    else:
        profiles = participant_payload.get('participants', [])
        participant_total = sum(
            profile.get('message_count', 0)
            for profile in profiles
            if isinstance(profile, dict)
        )
        check('participants.message_count', expected_participant_messages, participant_total)

    actual_vectors = _read_vector_count(dataset_dir) if vector_count is _AUTO_VECTOR_COUNT else vector_count
    if actual_vectors is None:
        if expected_messages:
            errors.append({
                'check': 'vectors.count',
                'expected': expected_messages,
                'actual': 'unavailable',
            })
    else:
        check('vectors.count', expected_messages, actual_vectors)

    current_snapshot = build_source_snapshot(dataset_dir)
    history = dataset_meta.get('export_history', []) if dataset_meta else []
    if history and isinstance(history[-1], dict):
        latest_snapshot = history[-1].get('source_snapshot', {})
        if latest_snapshot != current_snapshot:
            warnings.append({
                'check': 'export.latest_snapshot',
                'expected': current_snapshot,
                'actual': latest_snapshot,
                'status': 'stale',
            })

    if export_dir is not None:
        export_meta = _read_json(export_dir / 'metadata.json')
        if export_meta is None:
            errors.append({
                'check': 'export.metadata',
                'expected': 'valid JSON',
                'actual': 'missing/invalid',
            })
        else:
            check('export.source_snapshot', current_snapshot, export_meta.get('source_snapshot'))
            if history and isinstance(history[-1], dict):
                check(
                    'export.history_snapshot',
                    export_meta.get('source_snapshot'),
                    history[-1].get('source_snapshot'),
                )

    return {
        'ok': not errors,
        'errors': errors,
        'warnings': warnings,
        'counts': {
            'source_files': len(source_files),
            'messages': expected_messages,
            'assistant_turns': expected_assistant,
            'participant_messages': participant_total,
            'vectors': actual_vectors,
        },
        'source_snapshot': current_snapshot,
    }


def print_report(result: dict, *, strict: bool = True) -> bool:
    """Print a compact invariant report and return whether strict checks passed."""
    if result['errors']:
        print('   ❌ Dataset invariant failure:')
        for error in result['errors']:
            print(
                f'      - {error["check"]}: expected {error["expected"]!r}, '
                f'found {error["actual"]!r}'
            )
    else:
        counts = result['counts']
        print(
            '   ✅ Dataset invariants: '
            f'{counts["messages"]} messages, {counts["participant_messages"]} participant turns, '
            f'{counts["vectors"] if counts["vectors"] is not None else "n/a"} vectors'
        )
    for warning in result['warnings']:
        print(f'   ⚠️  {warning["check"]}: previous export is stale')
    return result['ok'] or not strict
