#!/usr/bin/env python3
"""
Unified ingestion pipeline for persona-knowledge.

Dispatches to the appropriate source adapter, runs PII scanning,
content-hash deduplication, writes to MemPalace, extracts KG triples,
and backs up raw data to sources/.

Usage:
    python scripts/ingest.py --slug sam --source ~/whatsapp-export.txt --persona-name "Samantha"
    python scripts/ingest.py --slug sam --source ~/twitter-archive/ --persona-name "Sam"
    python scripts/ingest.py --slug sam --source data.jsonl --adapter universal
    python scripts/ingest.py --slug sam --source gbrain-export.json --entity "Samantha"
"""

import argparse
import difflib
import hashlib
import json
import math
import os
import re
import sqlite3
import sys
import time
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

try:
    from .runtime import configure_safe_output
    from .kg_extraction import canonical_known_identity, extract_content_facts
    from .pii import PII_PATTERNS
    from .dataset_invariants import print_report as print_invariant_report
    from .dataset_invariants import validate_dataset
    from .source_reconciliation import quarantine_sources
except ImportError:
    from runtime import configure_safe_output
    from kg_extraction import canonical_known_identity, extract_content_facts
    from pii import PII_PATTERNS
    from dataset_invariants import print_report as print_invariant_report
    from dataset_invariants import validate_dataset
    from source_reconciliation import quarantine_sources

# Resolve adapters relative to this script's parent directory
SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SKILL_DIR))

from adapters import detect_adapter
KNOWLEDGE_ROOT = Path(os.environ.get(
    'OPENPERSONA_KNOWLEDGE',
    Path.home() / '.openpersona' / 'knowledge'
))

SOURCE_EQUIVALENCE_MIN_MESSAGES = 20
SOURCE_EQUIVALENCE_MIN_OVERLAP = 0.95
SOURCE_EQUIVALENCE_MIN_SIZE_RATIO = 0.90


def main(argv: list[str] | None = None, *, knowledge_root: Path | None = None):
    configure_safe_output()
    parser = argparse.ArgumentParser(description='Ingest data into a persona dataset')
    parser.add_argument('--slug', required=True, help='Persona dataset slug')
    parser.add_argument('--source', help='Path to source file or directory')
    parser.add_argument('--adapter', help='Force specific adapter (universal/chat_export/social)')
    parser.add_argument('--persona-name', default='', help='Persona display name (for role detection)')
    parser.add_argument(
        '--persona-exact',
        action='store_true',
        help='Match persona sender exactly after participant preflight',
    )
    parser.add_argument('--since', help='Only ingest data after this date (ISO 8601)')
    parser.add_argument('--entity', help='Entity name for GBrain JSON export')
    parser.add_argument('--dry-run', action='store_true', help='Parse and report without writing')
    equivalent_action = parser.add_mutually_exclusive_group()
    equivalent_action.add_argument(
        '--allow-equivalent-source',
        action='store_true',
        help='Ingest even when an equivalent active source backup is detected',
    )
    equivalent_action.add_argument(
        '--reconcile-equivalent-source',
        action='store_true',
        help='Confirm replacement of equivalent active backups using recoverable quarantine',
    )
    maintenance = parser.add_mutually_exclusive_group()
    maintenance.add_argument(
        '--rebuild-kg',
        action='store_true',
        help='Rebuild Knowledge Graph from stored sources without re-ingesting',
    )
    maintenance.add_argument(
        '--rebuild-vectors',
        action='store_true',
        help='Rebuild MemPalace vectors and participant metadata from stored sources',
    )
    maintenance.add_argument(
        '--migrate-vector-metadata',
        action='store_true',
        help='Update persisted vector metadata without recomputing embeddings',
    )

    args = parser.parse_args(argv)

    dataset_dir = (knowledge_root or KNOWLEDGE_ROOT) / args.slug
    if not dataset_dir.exists():
        print(f'❌ Dataset not found: {dataset_dir}', file=sys.stderr)
        print(f'   Run: python scripts/init_knowledge.py --slug {args.slug} --name "..."', file=sys.stderr)
        sys.exit(1)

    if args.rebuild_kg:
        messages = _load_stored_messages(dataset_dir)
        if not messages:
            print('⚠️  No stored messages available for KG rebuild.')
            return
        print(f'🔄 Rebuilding Knowledge Graph from {len(messages)} stored messages...')
        cleared = _clear_managed_kg(dataset_dir)
        print(f'   Cleared: {cleared} managed relationships')
        profiles = _write_participant_profiles(dataset_dir, messages)
        canonical_names = {profile['name'] for profile in profiles}
        pruned = _prune_invalid_kg_entities(dataset_dir, canonical_names)
        print(f'   Pruned: {pruned} invalid or identity-shadow orphan entities')
        kg_stats = _extract_kg_triples(dataset_dir, messages)
        _set_kg_stats(dataset_dir, kg_stats)
        invariants_ok = print_invariant_report(validate_dataset(dataset_dir))
        print(
            f'✅ Knowledge Graph rebuilt: {kg_stats["entities"]} entities, '
            f'{kg_stats["relationships"]} relationships'
        )
        if not invariants_ok:
            sys.exit(2)
        return

    if args.rebuild_vectors:
        messages = _load_stored_messages(dataset_dir)
        if not messages:
            print('⚠️  No stored messages available for vector rebuild.')
            return
        print(f'🔄 Rebuilding MemPalace from {len(messages)} stored messages...')
        removed = _prune_mempalace(dataset_dir, args.slug, messages)
        print(f'   Pruned: {removed} stale vectors')
        stored = _store_in_mempalace(
            dataset_dir,
            args.slug,
            messages,
            show_progress=True,
        )
        _write_participant_profiles(dataset_dir, messages)
        invariants_ok = print_invariant_report(validate_dataset(dataset_dir))
        print(f'✅ MemPalace rebuilt: {stored} messages with participant metadata')
        if not invariants_ok:
            sys.exit(2)
        return

    if args.migrate_vector_metadata:
        messages = _load_stored_messages(dataset_dir)
        if not messages:
            print('⚠️  No stored messages available for vector metadata migration.')
            return
        result = _migrate_mempalace_metadata(
            dataset_dir,
            args.slug,
            messages,
            apply=not args.dry_run,
        )
        action = 'would update' if args.dry_run else 'updated'
        print(
            f'✅ Vector metadata migration: {result["changed"]} {action}, '
            f'{result["unchanged"]} unchanged, 0 embeddings recomputed'
        )
        if args.dry_run:
            return
        _write_participant_profiles(dataset_dir, messages)
        if not print_invariant_report(validate_dataset(dataset_dir)):
            sys.exit(2)
        return

    # --- Resolve adapter ---
    adapter_name = args.adapter
    if not adapter_name and args.source:
        adapter_name = detect_adapter(args.source)
    if not adapter_name:
        print('❌ Cannot detect adapter. Specify --adapter explicitly.', file=sys.stderr)
        sys.exit(1)

    # --- Load adapter and parse ---
    adapter_module = _load_adapter(adapter_name)
    print(f'📥 Ingesting via [{adapter_name}] adapter...')

    parse_kwargs = {
        'persona_name': args.persona_name,
        'persona_exact': args.persona_exact,
        'since': args.since,
    }
    if args.entity:
        parse_kwargs['entity'] = args.entity

    source_path = args.source or ''
    messages = adapter_module.parse(source_path, **parse_kwargs)
    messages, rejected_notices = _reject_invalid_chat_senders(messages)

    if not messages:
        if rejected_notices:
            print(f'   Rejected: {rejected_notices} invalid chat system notices')
        print('⚠️  No messages parsed from source.')
        return

    print(f'   Parsed: {len(messages)} messages')
    if rejected_notices:
        print(f'   Rejected: {rejected_notices} invalid chat system notices')

    equivalent_sources = _find_equivalent_sources(dataset_dir, messages)
    replacement_matches = []
    if equivalent_sources:
        print('   ⚠️  Equivalent active source detected:')
        for match in equivalent_sources:
            print(
                f'      - {match["filename"]}: {match["overlap"]}/{match["smaller"]} '
                f'messages overlap ({match["coverage"]:.1%}), '
                f'size ratio {match["size_ratio"]:.1%}'
            )
        if args.reconcile_equivalent_source:
            replacement_matches = equivalent_sources
            print('   Confirmed reconciliation plan:')
            print('      - quarantine equivalent active backups')
            print('      - store incoming source as authoritative replacement')
            print('      - rebuild vectors, participant profiles, and managed KG')
            if args.dry_run:
                pii_flags = scan_pii(messages)
                _report_dry_run(messages, adapter_name, pii_flags)
                print('   Dry run: reconciliation not applied.')
                return
        elif not args.allow_equivalent_source:
            print('   Ingestion stopped before writing any data.')
            print(
                '   Pass --reconcile-equivalent-source to confirm safe replacement, '
                'or --allow-equivalent-source to keep both.'
            )
            sys.exit(2)
        else:
            print('   Override accepted: continuing without reconciling existing backups.')
    elif args.reconcile_equivalent_source:
        print('   No equivalent active source found; reconciliation not applied.', file=sys.stderr)
        sys.exit(2)

    # --- PII scan ---
    pii_flags = scan_pii(messages)
    if pii_flags:
        print(f'   ⚠️  PII detected: {", ".join(sorted(pii_flags))}')
    else:
        print(f'   PII: none detected')

    if replacement_matches:
        _run_equivalent_source_reconciliation(
            dataset_dir,
            args.slug,
            messages,
            replacement_matches,
            adapter_name,
            args.source,
            pii_flags,
        )
        return

    # --- Dedup ---
    existing_hashes = _load_existing_hashes(dataset_dir)
    new_messages, dup_count = dedup_messages(messages, existing_hashes)
    if dup_count:
        print(f'   Dedup: {dup_count} duplicates skipped')
    print(f'   New: {len(new_messages)} messages to ingest')

    if not new_messages:
        print('✅ Nothing new to ingest.')
        return

    if args.dry_run:
        _report_dry_run(new_messages, adapter_name, pii_flags)
        return

    # --- Store in MemPalace ---
    _store_in_mempalace(dataset_dir, args.slug, new_messages)

    # --- Extract KG triples ---
    kg_stats = _extract_kg_triples(dataset_dir, new_messages)

    # Recompute profiles from durable backups plus this batch. This is
    # idempotent when ingestion is retried after a later failure.
    profile_messages = _load_stored_messages(dataset_dir) + new_messages
    profile_messages, _ = dedup_messages(profile_messages, set())
    _write_participant_profiles(dataset_dir, profile_messages)

    # Write the dedup source backup only after both storage layers succeed.
    # MemPalace upserts and KG triples are idempotent, so a failed run can be
    # retried without incorrectly marking unstored messages as duplicates.
    source_filename = _write_sources_backup(
        dataset_dir, new_messages, adapter_name, args.source, pii_flags
    )

    # --- Update dataset.json stats ---
    _update_stats(dataset_dir, new_messages, kg_stats)
    invariants_ok = print_invariant_report(validate_dataset(dataset_dir))

    # --- Report ---
    assistant_turns = sum(1 for m in new_messages if m['role'] == 'assistant')
    print(f'\n✅ {source_filename} → {len(new_messages)} messages ({assistant_turns} assistant turns)')
    pii_str = ', '.join(sorted(pii_flags)) if pii_flags else 'none detected'
    print(f'   PII: {pii_str}')
    print(f'   KG: {kg_stats["entities"]} entities, {kg_stats["relationships"]} relationships')
    print(f'   → sources/{source_filename}')
    if not invariants_ok:
        sys.exit(2)


def _load_adapter(name: str):
    """Dynamically import an adapter module."""
    import importlib
    try:
        return importlib.import_module(f'adapters.{name}')
    except ImportError as e:
        print(f'❌ Adapter not found: {name} ({e})', file=sys.stderr)
        sys.exit(1)


def _reject_invalid_chat_senders(messages: list[dict]) -> tuple[list[dict], int]:
    """Drop parser artifacts that would create fake chat participants."""
    from adapters.chat_export import is_whatsapp_system_notice

    accepted = []
    rejected = 0
    for message in messages:
        metadata = message.get('metadata', {})
        sender = str(metadata.get('sender', '')).strip() if isinstance(metadata, dict) else ''
        invalid_structure = bool(sender and ('\n' in sender or '\r' in sender or len(sender) > 100))
        if sender and (invalid_structure or is_whatsapp_system_notice(sender)):
            rejected += 1
            continue
        accepted.append(message)
    return accepted, rejected


# --- PII Scanning ---

def scan_pii(messages: list[dict]) -> set[str]:
    flags = set()
    for msg in messages:
        content = msg.get('content', '')
        for pattern, label in PII_PATTERNS:
            if pattern.search(content):
                flags.add(label)
    return flags


# --- Deduplication ---

def _content_hash(msg: dict) -> str:
    key = f'{msg["role"]}:{msg["content"]}'
    if msg.get('source_type') == 'user_context':
        metadata = msg.get('metadata', {})
        if not isinstance(metadata, dict):
            metadata = {}
        key += ':' + ':'.join((
            str(metadata.get('subject', '')).casefold().strip(),
            str(metadata.get('record_kind', '')).casefold().strip(),
            str(metadata.get('authority', '')).casefold().strip(),
        ))
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def _load_existing_hashes(
    dataset_dir: Path,
    *,
    exclude: set[str] | None = None,
) -> set[str]:
    hashes = set()
    sources_dir = dataset_dir / 'sources'
    for jsonl_file in sources_dir.glob('*.jsonl'):
        if exclude and jsonl_file.name in exclude:
            continue
        with jsonl_file.open(encoding='utf-8') as source:
            for line in source:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    hashes.add(_content_hash(obj))
                except (json.JSONDecodeError, KeyError):
                    continue
    return hashes


def _load_stored_messages(dataset_dir: Path) -> list[dict]:
    """Load unique source-backup messages for non-destructive rebuilds."""
    messages = []
    seen = set()
    for jsonl_file in sorted((dataset_dir / 'sources').glob('*.jsonl')):
        with jsonl_file.open(encoding='utf-8') as source:
            for line in source:
                try:
                    message = json.loads(line)
                    content_hash = _content_hash(message)
                except (json.JSONDecodeError, KeyError):
                    continue
                if content_hash in seen:
                    continue
                seen.add(content_hash)
                messages.append(message)
    return messages


def dedup_messages(messages: list[dict], existing_hashes: set[str]) -> tuple[list[dict], int]:
    seen = set(existing_hashes)
    new_messages = []
    dup_count = 0

    for msg in messages:
        h = _content_hash(msg)
        if h in seen:
            dup_count += 1
            continue
        seen.add(h)
        new_messages.append(msg)

    return new_messages, dup_count


def _equivalence_fingerprint(message: dict) -> str:
    """Hash message text independent of adapter role/metadata representation."""
    content = unicodedata.normalize('NFKC', str(message.get('content', '')))
    normalized = re.sub(r'\s+', ' ', content).strip().casefold()
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest() if normalized else ''


def _equivalence_counter(messages: list[dict]) -> Counter:
    """Build a content multiset after removing exact role/content duplicates."""
    unique_messages, _ = dedup_messages(messages, set())
    fingerprints = (_equivalence_fingerprint(message) for message in unique_messages)
    return Counter(fingerprint for fingerprint in fingerprints if fingerprint)


def _read_source_messages(source_path: Path) -> list[dict]:
    messages = []
    with source_path.open(encoding='utf-8') as source:
        for line in source:
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(message, dict) and message.get('content'):
                messages.append(message)
    return messages


def _find_equivalent_sources(dataset_dir: Path, messages: list[dict]) -> list[dict]:
    """Find active backups representing substantially the same message collection."""
    candidate = _equivalence_counter(messages)
    candidate_count = sum(candidate.values())
    if not candidate_count:
        return []

    matches = []
    for source_path in sorted((dataset_dir / 'sources').glob('*.jsonl')):
        existing = _equivalence_counter(_read_source_messages(source_path))
        existing_count = sum(existing.values())
        if not existing_count:
            continue

        overlap = sum((candidate & existing).values())
        smaller = min(candidate_count, existing_count)
        larger = max(candidate_count, existing_count)
        coverage = overlap / smaller
        size_ratio = smaller / larger

        if smaller < SOURCE_EQUIVALENCE_MIN_MESSAGES:
            equivalent = candidate == existing
        else:
            equivalent = (
                coverage >= SOURCE_EQUIVALENCE_MIN_OVERLAP
                and size_ratio >= SOURCE_EQUIVALENCE_MIN_SIZE_RATIO
            )
        if equivalent:
            matches.append({
                'filename': source_path.name,
                'candidate_messages': candidate_count,
                'existing_messages': existing_count,
                'overlap': overlap,
                'smaller': smaller,
                'coverage': coverage,
                'size_ratio': size_ratio,
            })
    return matches


def _run_equivalent_source_reconciliation(
    dataset_dir: Path,
    slug: str,
    messages: list[dict],
    matches: list[dict],
    adapter_name: str,
    source_path: str | None,
    pii_flags: set[str],
) -> dict:
    """Replace equivalent active backups, then rebuild every affected derived layer."""
    matched_names = {match['filename'] for match in matches}
    remaining_hashes = _load_existing_hashes(dataset_dir, exclude=matched_names)
    replacement_messages, duplicate_count = dedup_messages(messages, remaining_hashes)
    if not replacement_messages:
        raise RuntimeError('Replacement source contains no messages unique from retained sources')

    quarantine = quarantine_sources(
        dataset_dir,
        sorted(matched_names),
        reason='equivalent-source-preflight',
        replacement_source=source_path,
    )
    source_filename = _write_sources_backup(
        dataset_dir,
        replacement_messages,
        adapter_name,
        source_path,
        pii_flags,
    )

    authoritative_messages = _load_stored_messages(dataset_dir)
    removed_vectors = _prune_mempalace(dataset_dir, slug, authoritative_messages)
    stored_vectors = _store_in_mempalace(
        dataset_dir,
        slug,
        authoritative_messages,
        show_progress=True,
    )
    cleared_relationships = _clear_managed_kg(dataset_dir)
    profiles = _write_participant_profiles(dataset_dir, authoritative_messages)
    canonical_names = {profile['name'] for profile in profiles}
    pruned_entities = _prune_invalid_kg_entities(dataset_dir, canonical_names)
    kg_stats = _extract_kg_triples(dataset_dir, authoritative_messages)
    _replace_stats(dataset_dir, authoritative_messages, kg_stats)
    invariants = validate_dataset(dataset_dir)
    invariants_ok = print_invariant_report(invariants)

    print('\n✅ Equivalent source reconciliation complete')
    print(f'   Quarantined: {", ".join(quarantine["quarantined"])}')
    print(f'   Quarantine: {quarantine["quarantine_dir"]}')
    print(f'   Replacement: sources/{source_filename}')
    print(
        f'   Messages: {len(authoritative_messages)} '
        f'({duplicate_count} retained-source duplicates skipped)'
    )
    print(f'   Vectors: {stored_vectors} stored, {removed_vectors} stale pruned')
    print(f'   KG: {cleared_relationships} cleared, {pruned_entities} entities pruned')
    if not invariants_ok:
        sys.exit(2)
    return {
        'quarantine': quarantine,
        'source_filename': source_filename,
        'messages': len(authoritative_messages),
        'vectors': stored_vectors,
        'kg_stats': kg_stats,
        'invariants': invariants,
    }


# --- Sources backup ---

def _write_sources_backup(dataset_dir: Path, messages: list[dict], adapter_name: str,
                          source_path: str | None, pii_flags: set[str], *,
                          source_metadata: dict | None = None) -> str:
    sources_dir = dataset_dir / 'sources'
    sources_dir.mkdir(exist_ok=True)

    # Generate filename from source
    if source_path:
        base = Path(source_path).stem.lower()
        base = re.sub(r'[^a-z0-9_-]', '-', base)
    else:
        base = adapter_name

    ts = datetime.now().strftime('%Y%m%d')
    filename = f'{base}-{ts}.jsonl'

    # Avoid collision
    counter = 1
    while (sources_dir / filename).exists():
        filename = f'{base}-{ts}-{counter}.jsonl'
        counter += 1

    # Write JSONL
    with open(sources_dir / filename, 'w', encoding='utf-8') as f:
        for msg in messages:
            f.write(json.dumps(msg, ensure_ascii=False) + '\n')

    # Update source index
    index_path = sources_dir / '.source-index.json'
    if index_path.exists():
        index = json.loads(index_path.read_text(encoding='utf-8'))
    else:
        index = {'files': [], 'last_updated': ''}

    source_entry = {
        'filename': filename,
        'adapter': adapter_name,
        'source': source_path or adapter_name,
        'imported_at': datetime.now(timezone.utc).isoformat(),
        'lines': len(messages),
        'assistant_turns': sum(1 for m in messages if m['role'] == 'assistant'),
        'content_hash': hashlib.sha256(
            ''.join(m['content'] for m in messages).encode()
        ).hexdigest()[:16],
        'pii_flags': sorted(pii_flags) if pii_flags else None,
    }
    if source_metadata:
        source_entry.update(source_metadata)
    index['files'].append(source_entry)
    index['last_updated'] = datetime.now(timezone.utc).isoformat()

    index_path.write_text(json.dumps(index, indent=2, ensure_ascii=False) + '\n')
    return filename


# --- MemPalace storage ---

HALL_ROUTING = {
    'obsidian': 'hall_facts',
    'markdown': 'hall_facts',
    'gbrain-export': 'hall_facts',
    'gbrain': 'hall_facts',
    'whatsapp': 'hall_voice',
    'telegram': 'hall_voice',
    'signal': 'hall_voice',
    'imessage': 'hall_voice',
    'twitter': 'hall_voice',
    'twitter-dm': 'hall_voice',
    'instagram': 'hall_voice',
    'instagram-dm': 'hall_voice',
    'csv': 'hall_facts',
    'plaintext': 'hall_facts',
    'pdf': 'hall_facts',
    'jsonl': 'hall_voice',
}


def _store_in_mempalace(
    dataset_dir: Path,
    slug: str,
    messages: list[dict],
    *,
    show_progress: bool = False,
    clock=None,
) -> int:
    palace_dir = dataset_dir / '.mempalace' / 'palace'

    try:
        from mempalace.palace import get_collection
    except ImportError as e:
        raise RuntimeError(
            'mempalace is required for ingestion; install it with: pip install mempalace'
        ) from e

    try:
        palace_dir.mkdir(parents=True, exist_ok=True)
        collection = get_collection(str(palace_dir), create=True)
    except Exception as e:
        raise RuntimeError(f'MemPalace initialization failed: {e}') from e

    stored = 0
    batch_size = 128
    clock = clock or time.monotonic
    started_at = clock() if show_progress else None
    for batch_start in range(0, len(messages), batch_size):
        batch = messages[batch_start:batch_start + batch_size]
        documents = []
        ids = []
        metadatas = []
        for msg in batch:
            documents.append(msg['content'])
            ids.append(_vector_id(slug, msg))
            metadatas.append(_vector_metadata(slug, msg))
        try:
            collection.upsert(
                documents=documents,
                ids=ids,
                metadatas=metadatas,
            )
            stored += len(batch)
            if show_progress:
                elapsed = max(clock() - started_at, 0.0)
                print(
                    f'   MemPalace: {_format_vector_progress(stored, len(messages), elapsed)}',
                    flush=True,
                )
        except Exception as e:
            raise RuntimeError(
                f'MemPalace storage failed after {stored}/{len(messages)} messages: {e}'
            ) from e

    print(f'   MemPalace: {stored}/{len(messages)} stored')
    return stored


def _format_duration(seconds: float | None) -> str:
    if seconds is None or not math.isfinite(seconds):
        return '--:--'
    total_seconds = max(0, math.ceil(seconds))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, remaining_seconds = divmod(remainder, 60)
    if hours:
        return f'{hours:02d}:{minutes:02d}:{remaining_seconds:02d}'
    return f'{minutes:02d}:{remaining_seconds:02d}'


def _format_vector_progress(stored: int, total: int, elapsed: float) -> str:
    percentage = (stored / total * 100) if total else 100.0
    if stored >= total:
        eta = 0.0
    elif stored and elapsed > 0:
        eta = (total - stored) / (stored / elapsed)
    else:
        eta = None
    return (
        f'{stored}/{total} ({percentage:.1f}%) | '
        f'elapsed {_format_duration(elapsed)} | ETA {_format_duration(eta)}'
    )


def _vector_id(slug: str, message: dict) -> str:
    return f'{slug}-{_content_hash(message)}'


def _vector_metadata(slug: str, message: dict) -> dict:
    """Build authoritative managed metadata without touching vector content."""
    message_metadata = message.get('metadata', {})
    if not isinstance(message_metadata, dict):
        message_metadata = {}
    source_type = message.get('source_type', message_metadata.get('type', ''))
    metadata = {
        'wing': slug,
        'room': source_type or 'general',
        'hall': HALL_ROUTING.get(source_type, 'hall_voice'),
        'role': message['role'],
        'source_file': message.get('source_file') or '',
        'source_type': source_type or '',
        'sender': str(message_metadata.get('sender', '')).strip(),
    }
    if message.get('timestamp'):
        metadata['authored_at'] = message['timestamp']
    for key in (
        'subject',
        'authored_by',
        'record_kind',
        'authority',
        'confidence',
        'source_sha256',
        'record_number',
        'imported_at',
    ):
        value = message_metadata.get(key)
        if isinstance(value, (str, int, float, bool)) and value != '':
            metadata[key] = value
    return metadata


def _migrate_mempalace_metadata(
    dataset_dir: Path,
    slug: str,
    messages: list[dict],
    *,
    apply: bool = True,
) -> dict:
    """Update metadata only; never submit documents or embeddings to Chroma."""
    try:
        from mempalace.palace import get_collection
    except ImportError as exc:
        raise RuntimeError(
            'mempalace is required for metadata migration; install it with: pip install mempalace'
        ) from exc

    collection = get_collection(
        str(dataset_dir / '.mempalace' / 'palace'),
        create=False,
    )
    expected = {
        _vector_id(slug, message): _vector_metadata(slug, message)
        for message in messages
    }
    result = collection.get(include=['metadatas'])
    ids = list(result.get('ids', []))
    metadatas = list(result.get('metadatas', []))
    if len(metadatas) < len(ids):
        metadatas.extend({} for _ in range(len(ids) - len(metadatas)))
    existing = {
        vector_id: dict(metadata or {})
        for vector_id, metadata in zip(ids, metadatas)
    }

    missing = sorted(set(expected) - set(existing))
    stale = sorted(set(existing) - set(expected))
    if missing or stale:
        raise RuntimeError(
            'Vector metadata migration requires identical vector IDs; '
            f'missing={len(missing)}, stale={len(stale)}. Run --rebuild-vectors.'
        )

    changed = []
    for vector_id, desired in expected.items():
        merged = {**existing[vector_id], **desired}
        if merged != existing[vector_id]:
            changed.append((vector_id, merged, desired))

    if apply:
        batch_size = 500
        for start in range(0, len(changed), batch_size):
            batch = changed[start:start + batch_size]
            collection.update(
                ids=[item[0] for item in batch],
                metadatas=[item[1] for item in batch],
            )

        if changed:
            verify = collection.get(
                ids=[item[0] for item in changed],
                include=['metadatas'],
            )
            verified = {
                vector_id: dict(metadata or {})
                for vector_id, metadata in zip(
                    verify.get('ids', []),
                    verify.get('metadatas', []),
                )
            }
            failed = [
                vector_id
                for vector_id, _merged, desired in changed
                if not all(
                    verified.get(vector_id, {}).get(key) == value
                    for key, value in desired.items()
                )
            ]
            if failed:
                raise RuntimeError(f'Vector metadata verification failed for {len(failed)} records')

    return {
        'total': len(expected),
        'changed': len(changed),
        'updated': len(changed) if apply else 0,
        'unchanged': len(expected) - len(changed),
        'embeddings_recomputed': 0,
    }


def _prune_mempalace(dataset_dir: Path, slug: str, messages: list[dict]) -> int:
    """Remove dataset vectors no longer present in authoritative source backups."""
    try:
        from mempalace.palace import get_collection
    except ImportError as exc:
        raise RuntimeError(
            'mempalace is required for vector rebuild; install it with: pip install mempalace'
        ) from exc

    collection = get_collection(
        str(dataset_dir / '.mempalace' / 'palace'),
        create=True,
    )
    expected = {_vector_id(slug, message) for message in messages}
    result = collection.get(where={'wing': slug}, include=[])
    stale = [vector_id for vector_id in result.get('ids', []) if vector_id not in expected]
    batch_size = 500
    for start in range(0, len(stale), batch_size):
        collection.delete(ids=stale[start:start + batch_size])
    return len(stale)


# --- Knowledge Graph extraction ---

_ROMANTIC_PARTNER_PATTERN = re.compile(
    r'\b(?:mi\s+(?:novia|novio|pareja)|amor\s+de\s+mi\s+vida|quiero\s+todo\s+contigo)\b',
    re.IGNORECASE,
)


def _extract_kg_triples(dataset_dir: Path, messages: list[dict]) -> dict:
    """Extract entities and relationships from message content."""
    slug = dataset_dir.name
    entities = set()
    relationships_by_key = {}

    def add_relationship(
        source: str,
        target: str,
        rel_type: str,
        msg: dict,
        *,
        confidence: float = 1.0,
    ):
        source = source.strip()
        target = target.strip()
        if not source or not target or source.casefold() == target.casefold():
            return
        if source.casefold() != slug.casefold():
            entities.add(source)
        if target.casefold() != slug.casefold():
            entities.add(target)
        key = (source.casefold(), target.casefold(), rel_type)
        candidate = {
            'from': source,
            'to': target,
            'type': rel_type,
            'confidence': confidence,
            'timestamp': msg.get('timestamp'),
            'source': msg.get('source_file'),
        }
        current = relationships_by_key.get(key)
        if current is None or confidence > current['confidence']:
            relationships_by_key[key] = candidate

    participant_messages = {}
    assistant_names = {}
    user_names = {}
    for msg in messages:
        sender = str(msg.get('metadata', {}).get('sender', '')).strip()
        if not sender:
            continue
        key = sender.casefold()
        participant_messages.setdefault(key, msg)
        if msg.get('role') == 'assistant':
            assistant_names.setdefault(key, sender)
        else:
            user_names.setdefault(key, sender)

    participants = {**user_names, **assistant_names}
    for key, name in participants.items():
        entities.add(name)
        add_relationship(name, slug, 'participant_in', participant_messages[key], confidence=1.0)

    for assistant_key, assistant_name in assistant_names.items():
        for user_key, user_name in user_names.items():
            if assistant_key != user_key:
                add_relationship(
                    assistant_name,
                    user_name,
                    'communicates_with',
                    participant_messages[user_key],
                    confidence=1.0,
                )

    if len(assistant_names) == 1 and len(user_names) == 1:
        assistant_name = next(iter(assistant_names.values()))
        user_name = next(iter(user_names.values()))
        romantic_evidence = next(
            (
                msg for msg in messages
                if _ROMANTIC_PARTNER_PATTERN.search(msg.get('content', ''))
            ),
            None,
        )
        if romantic_evidence:
            add_relationship(
                assistant_name,
                user_name,
                'romantic_partner',
                romantic_evidence,
                confidence=0.95,
            )

    extracted = extract_content_facts(messages, set(participants.values()))
    entities.update(extracted['entities'])
    for relationship in extracted['relationships']:
        add_relationship(
            relationship['from'],
            relationship['to'] or slug,
            relationship['type'],
            relationship,
            confidence=relationship['confidence'],
        )

    relationships = list(relationships_by_key.values())

    # Write to KG if available
    palace_dir = dataset_dir / '.mempalace' / 'palace'
    persisted_stats = _write_kg(palace_dir, entities, relationships)

    extracted_stats = {
        'entities': len(entities),
        'relationships': len(relationships),
    }
    return persisted_stats if isinstance(persisted_stats, dict) else extracted_stats


def _build_participant_profiles(messages: list[dict]) -> list[dict]:
    """Aggregate stable, independent identities from exact chat senders."""
    profiles = {}
    for msg in messages:
        sender = str(msg.get('metadata', {}).get('sender', '')).strip()
        if not sender:
            continue
        key = sender.casefold()
        profile = profiles.setdefault(key, {
            'name': sender,
            'message_count': 0,
            'assistant_messages': 0,
            'user_messages': 0,
            'first_seen': None,
            'last_seen': None,
            'sources': set(),
        })
        profile['message_count'] += 1
        role_key = 'assistant_messages' if msg.get('role') == 'assistant' else 'user_messages'
        profile[role_key] += 1
        timestamp = msg.get('timestamp')
        if timestamp:
            if profile['first_seen'] is None or timestamp < profile['first_seen']:
                profile['first_seen'] = timestamp
            if profile['last_seen'] is None or timestamp > profile['last_seen']:
                profile['last_seen'] = timestamp
        source = msg.get('source_file')
        if source:
            profile['sources'].add(source)

    result = []
    for profile in profiles.values():
        profile['identity_type'] = (
            'persona' if profile['assistant_messages'] else 'contact'
        )
        profile['sources'] = sorted(profile['sources'])
        result.append(profile)
    return sorted(result, key=lambda item: item['name'].casefold())


def _write_participant_profiles(dataset_dir: Path, messages: list[dict]) -> list[dict]:
    """Replace participant profiles using the complete deduplicated dataset."""
    profiles = _build_participant_profiles(messages)
    aliases = _load_identity_aliases(dataset_dir)
    inferred_aliases = _infer_identity_aliases(profiles, messages)
    try:
        dataset_meta = json.loads((dataset_dir / 'dataset.json').read_text(encoding='utf-8'))
    except (FileNotFoundError, json.JSONDecodeError):
        dataset_meta = {}
    for profile in profiles:
        profile_aliases = {profile['name']}
        if profile['identity_type'] == 'persona':
            display_name = str(dataset_meta.get('name', '')).strip()
            if display_name:
                profile_aliases.add(display_name)
        profile_aliases.update(aliases.get(profile['name'].casefold(), []))
        profile_aliases.update(inferred_aliases.get(profile['name'].casefold(), []))
        profile['aliases'] = sorted(profile_aliases, key=str.casefold)
    payload = {
        'schema_version': 2,
        'updated_at': datetime.now(timezone.utc).isoformat(),
        'participants': profiles,
    }
    (dataset_dir / 'participants.json').write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + '\n',
        encoding='utf-8',
    )
    return profiles


def _infer_identity_aliases(
    profiles: list[dict],
    messages: list[dict],
) -> dict[str, list[str]]:
    """Infer repeated name variants without merging distinct participants."""
    aliases = {}
    authored_by = {
        str(message.get('metadata', {}).get('sender', '')).casefold()
        for message in messages
    }
    tokens = Counter(
        token
        for message in messages
        for token in re.findall(r'\b[A-Za-zÁÉÍÓÚÑÜáéíóúñü]{3,}\b', message.get('content', ''))
    )
    for profile in profiles:
        canonical = profile['name']
        normalized = canonical.casefold()
        if profile.get('identity_type') != 'contact' or len(normalized) < 4:
            continue
        prefix_length = max(3, min(5, len(normalized) // 2))
        prefix = normalized[:prefix_length]
        candidates = []
        for token, count in tokens.items():
            token_normalized = token.casefold()
            if count < 2 or token_normalized in authored_by:
                continue
            if not token_normalized.startswith(prefix):
                continue
            similarity = difflib.SequenceMatcher(None, normalized, token_normalized).ratio()
            if similarity >= 0.45 and token_normalized != normalized:
                candidates.append(token)
        if candidates:
            aliases[normalized] = sorted(set(candidates), key=str.casefold)
    return aliases


def _load_identity_aliases(dataset_dir: Path) -> dict[str, list[str]]:
    """Load optional private canonical-name aliases for cross-source identity matching."""
    alias_path = dataset_dir / 'identity_aliases.json'
    try:
        payload = json.loads(alias_path.read_text(encoding='utf-8'))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    canonical = payload.get('canonical', {})
    if not isinstance(canonical, dict):
        return {}
    result = {}
    for name, values in canonical.items():
        if not isinstance(values, list):
            continue
        result[str(name).casefold()] = [
            str(value).strip() for value in values if str(value).strip()
        ]
    return result


def _clear_managed_kg(dataset_dir: Path) -> int:
    """Remove only triples owned by this ingestion pipeline before rebuild."""
    db_path = dataset_dir / '.mempalace' / 'palace' / 'knowledge_graph.sqlite3'
    if not db_path.exists():
        return 0
    connection = sqlite3.connect(db_path)
    try:
        cursor = connection.execute(
            'DELETE FROM triples WHERE adapter_name = ?',
            ('persona-knowledge',),
        )
        connection.commit()
        return max(cursor.rowcount, 0)
    except sqlite3.OperationalError:
        return 0
    finally:
        connection.close()


def _prune_invalid_kg_entities(
    dataset_dir: Path,
    canonical_names: set[str] | None = None,
) -> int:
    """Delete malformed or canonical-identity-shadow orphan entities."""
    db_path = dataset_dir / '.mempalace' / 'palace' / 'knowledge_graph.sqlite3'
    if not db_path.exists():
        return 0
    connection = sqlite3.connect(db_path)
    try:
        rows = connection.execute(
            "SELECT id, name FROM entities "
            "WHERE id NOT IN (SELECT subject FROM triples) "
            "AND id NOT IN (SELECT object FROM triples)"
        ).fetchall()
        remove_ids = []
        for entity_id, name in rows:
            malformed = len(name) > 120 or '\n' in name or '\r' in name
            canonical = canonical_known_identity(name, canonical_names or set())
            identity_shadow = canonical is not None and canonical.casefold() != name.casefold()
            if malformed or identity_shadow:
                remove_ids.append((entity_id,))
        if remove_ids:
            connection.executemany('DELETE FROM entities WHERE id = ?', remove_ids)
        connection.commit()
        return len(remove_ids)
    except sqlite3.OperationalError:
        return 0
    finally:
        connection.close()


def _write_kg(palace_dir: Path, entities: set[str], relationships: list[dict]):
    """Write extracted entities/relationships to the Knowledge Graph."""
    try:
        from mempalace.knowledge_graph import KnowledgeGraph
        palace_dir.mkdir(parents=True, exist_ok=True)
        kg = KnowledgeGraph(db_path=str(palace_dir / 'knowledge_graph.sqlite3'))

        try:
            for entity in entities:
                kg.add_entity(entity, entity_type='person')

            for rel in relationships:
                kg.add_triple(
                    subject=rel['from'],
                    predicate=rel['type'],
                    obj=rel.get('to', ''),
                    valid_from=_kg_valid_from(rel.get('timestamp')),
                    confidence=float(rel.get('confidence', 1.0)),
                    source_file=rel.get('source'),
                    adapter_name='persona-knowledge',
                )
            stats = kg.stats()
            return {
                'entities': stats.get('entities', len(entities)),
                'relationships': stats.get('triples', len(relationships)),
            }
        finally:
            kg.close()

    except ImportError:
        # Store as fallback JSON
        kg_file = palace_dir.parent / 'kg-pending.json'
        pending = []
        if kg_file.exists():
            try:
                pending = json.loads(kg_file.read_text())
            except json.JSONDecodeError:
                pass

        for entity in entities:
            pending.append({'_entry': 'entity', 'name': entity, 'entity_type': 'person'})
        for rel in relationships:
            pending.append({'_entry': 'relationship', **rel})

        kg_file.write_text(json.dumps(pending, indent=2, ensure_ascii=False) + '\n')
        return {
            'entities': len(entities),
            'relationships': len(relationships),
        }


def _kg_valid_from(timestamp: str | None) -> str | None:
    """Use date precision when a source timestamp has no trustworthy timezone."""
    if not timestamp:
        return None
    match = re.match(r'^(\d{4}-\d{2}-\d{2})', str(timestamp))
    return match.group(1) if match else None


# --- Stats update ---

def _update_stats(dataset_dir: Path, messages: list[dict], kg_stats: dict):
    meta_path = dataset_dir / 'dataset.json'
    try:
        meta = json.loads(meta_path.read_text(encoding='utf-8'))
    except (FileNotFoundError, json.JSONDecodeError):
        return

    stats = meta.setdefault('stats', {})
    stats['sources'] = stats.get('sources', 0) + 1
    stats['total_messages'] = stats.get('total_messages', 0) + len(messages)
    stats['assistant_turns'] = stats.get('assistant_turns', 0) + sum(
        1 for m in messages if m['role'] == 'assistant'
    )
    stats['kg_entities'] = kg_stats['entities']
    stats['kg_relationships'] = kg_stats['relationships']

    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + '\n')


def _replace_stats(dataset_dir: Path, messages: list[dict], kg_stats: dict):
    """Replace counters after authoritative source reconciliation."""
    meta_path = dataset_dir / 'dataset.json'
    try:
        meta = json.loads(meta_path.read_text(encoding='utf-8'))
    except (FileNotFoundError, json.JSONDecodeError):
        return

    stats = meta.setdefault('stats', {})
    stats['sources'] = len(list((dataset_dir / 'sources').glob('*.jsonl')))
    stats['total_messages'] = len(messages)
    stats['assistant_turns'] = sum(message.get('role') == 'assistant' for message in messages)
    stats['kg_entities'] = kg_stats['entities']
    stats['kg_relationships'] = kg_stats['relationships']
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + '\n')


def _set_kg_stats(dataset_dir: Path, kg_stats: dict):
    """Replace KG counters after an idempotent full rebuild."""
    meta_path = dataset_dir / 'dataset.json'
    try:
        meta = json.loads(meta_path.read_text(encoding='utf-8'))
    except (FileNotFoundError, json.JSONDecodeError):
        return

    stats = meta.setdefault('stats', {})
    stats['kg_entities'] = kg_stats['entities']
    stats['kg_relationships'] = kg_stats['relationships']
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + '\n')


# --- Dry run report ---

def _report_dry_run(messages: list[dict], adapter_name: str, pii_flags: set[str]):
    assistant = sum(1 for m in messages if m['role'] == 'assistant')
    user = sum(1 for m in messages if m['role'] == 'user')
    sources = set(m.get('source_type', '') for m in messages)

    print(f'\n📋 Dry run report:')
    print(f'   Adapter: {adapter_name}')
    print(f'   Messages: {len(messages)} ({assistant} assistant, {user} user)')
    print(f'   Source types: {", ".join(sources)}')
    print(f'   PII flags: {", ".join(sorted(pii_flags)) if pii_flags else "none"}')

    if messages:
        print(f'\n   Sample (first 3):')
        for msg in messages[:3]:
            content_preview = msg['content'][:80].replace('\n', ' ')
            print(f'     [{msg["role"]}] {content_preview}...')

    print(f'\n   ℹ️  Remove --dry-run to write to dataset.')


if __name__ == '__main__':
    main()
