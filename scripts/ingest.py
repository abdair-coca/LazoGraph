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
import os
import re
import sqlite3
import sys
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

# Resolve adapters relative to this script's parent directory
SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SKILL_DIR))

from adapters import detect_adapter

KNOWLEDGE_ROOT = Path(os.environ.get(
    'OPENPERSONA_KNOWLEDGE',
    Path.home() / '.openpersona' / 'knowledge'
))

# PII patterns (conservative — flag, don't block)
PII_PATTERNS = [
    (re.compile(r'\b\d{3}-\d{2}-\d{4}\b'), 'SSN'),
    (re.compile(r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b'), 'credit_card'),
    (re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b'), 'email'),
    (re.compile(r'\b(?:password|passwd|pwd)\s*[:=]\s*\S+', re.IGNORECASE), 'password'),
    (re.compile(r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b'), 'phone'),
]

SOURCE_EQUIVALENCE_MIN_MESSAGES = 20
SOURCE_EQUIVALENCE_MIN_OVERLAP = 0.95
SOURCE_EQUIVALENCE_MIN_SIZE_RATIO = 0.90


def main():
    parser = argparse.ArgumentParser(description='Ingest data into a persona dataset')
    parser.add_argument('--slug', required=True, help='Persona dataset slug')
    parser.add_argument('--source', help='Path to source file or directory')
    parser.add_argument('--adapter', help='Force specific adapter (universal/chat_export/social)')
    parser.add_argument('--persona-name', default='', help='Persona display name (for role detection)')
    parser.add_argument('--since', help='Only ingest data after this date (ISO 8601)')
    parser.add_argument('--entity', help='Entity name for GBrain JSON export')
    parser.add_argument('--dry-run', action='store_true', help='Parse and report without writing')
    parser.add_argument(
        '--allow-equivalent-source',
        action='store_true',
        help='Ingest even when an equivalent active source backup is detected',
    )
    parser.add_argument(
        '--rebuild-kg',
        action='store_true',
        help='Rebuild Knowledge Graph from stored sources without re-ingesting',
    )
    parser.add_argument(
        '--rebuild-vectors',
        action='store_true',
        help='Rebuild MemPalace vectors and participant metadata from stored sources',
    )

    args = parser.parse_args()

    dataset_dir = KNOWLEDGE_ROOT / args.slug
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
        pruned = _prune_invalid_kg_entities(dataset_dir)
        print(f'   Pruned: {pruned} invalid orphan entities')
        _write_participant_profiles(dataset_dir, messages)
        kg_stats = _extract_kg_triples(dataset_dir, messages)
        _set_kg_stats(dataset_dir, kg_stats)
        print(
            f'✅ Knowledge Graph rebuilt: {kg_stats["entities"]} entities, '
            f'{kg_stats["relationships"]} relationships'
        )
        return

    if args.rebuild_vectors:
        messages = _load_stored_messages(dataset_dir)
        if not messages:
            print('⚠️  No stored messages available for vector rebuild.')
            return
        print(f'🔄 Rebuilding MemPalace from {len(messages)} stored messages...')
        removed = _prune_mempalace(dataset_dir, args.slug, messages)
        print(f'   Pruned: {removed} stale vectors')
        stored = _store_in_mempalace(dataset_dir, args.slug, messages)
        _write_participant_profiles(dataset_dir, messages)
        print(f'✅ MemPalace rebuilt: {stored} messages with participant metadata')
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
    if equivalent_sources:
        print('   ⚠️  Equivalent active source detected:')
        for match in equivalent_sources:
            print(
                f'      - {match["filename"]}: {match["overlap"]}/{match["smaller"]} '
                f'messages overlap ({match["coverage"]:.1%}), '
                f'size ratio {match["size_ratio"]:.1%}'
            )
        if not args.allow_equivalent_source:
            print('   Ingestion stopped before writing any data.')
            print('   Review active backups or pass --allow-equivalent-source to continue intentionally.')
            sys.exit(2)
        print('   Override accepted: continuing without reconciling existing backups.')

    # --- PII scan ---
    pii_flags = scan_pii(messages)
    if pii_flags:
        print(f'   ⚠️  PII detected: {", ".join(sorted(pii_flags))}')
    else:
        print(f'   PII: none detected')

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

    # --- Report ---
    assistant_turns = sum(1 for m in new_messages if m['role'] == 'assistant')
    print(f'\n✅ {source_filename} → {len(new_messages)} messages ({assistant_turns} assistant turns)')
    pii_str = ', '.join(sorted(pii_flags)) if pii_flags else 'none detected'
    print(f'   PII: {pii_str}')
    print(f'   KG: {kg_stats["entities"]} entities, {kg_stats["relationships"]} relationships')
    print(f'   → sources/{source_filename}')


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
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def _load_existing_hashes(dataset_dir: Path) -> set[str]:
    hashes = set()
    sources_dir = dataset_dir / 'sources'
    for jsonl_file in sources_dir.glob('*.jsonl'):
        for line in jsonl_file.open(encoding='utf-8'):
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


# --- Sources backup ---

def _write_sources_backup(dataset_dir: Path, messages: list[dict], adapter_name: str,
                          source_path: str | None, pii_flags: set[str]) -> str:
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

    index['files'].append({
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
    })
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


def _store_in_mempalace(dataset_dir: Path, slug: str, messages: list[dict]) -> int:
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
    for batch_start in range(0, len(messages), batch_size):
        batch = messages[batch_start:batch_start + batch_size]
        documents = []
        ids = []
        metadatas = []
        for msg in batch:
            source_type = msg.get('source_type', msg.get('metadata', {}).get('type', ''))
            hall = HALL_ROUTING.get(source_type, 'hall_voice')
            documents.append(msg['content'])
            ids.append(f'{slug}-{_content_hash(msg)}')
            metadata = {
                'wing': slug,
                'room': source_type or 'general',
                'hall': hall,
                'role': msg['role'],
                'source_file': msg.get('source_file') or '',
                'source_type': source_type or '',
                'sender': str(msg.get('metadata', {}).get('sender', '')).strip(),
            }
            if msg.get('timestamp'):
                metadata['authored_at'] = msg['timestamp']
            metadatas.append(metadata)
        try:
            collection.upsert(
                documents=documents,
                ids=ids,
                metadatas=metadatas,
            )
            stored += len(batch)
        except Exception as e:
            raise RuntimeError(
                f'MemPalace storage failed after {stored}/{len(messages)} messages: {e}'
            ) from e

    print(f'   MemPalace: {stored}/{len(messages)} stored')
    return stored


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
    expected = {f'{slug}-{_content_hash(message)}' for message in messages}
    result = collection.get(where={'wing': slug}, include=[])
    stale = [vector_id for vector_id in result.get('ids', []) if vector_id not in expected]
    batch_size = 500
    for start in range(0, len(stale), batch_size):
        collection.delete(ids=stale[start:start + batch_size])
    return len(stale)


# --- Knowledge Graph extraction ---

# Simple multilingual entity/relationship patterns for automatic extraction
_NAME_TOKEN = r'[A-ZÁÉÍÓÚÑÜ][a-záéíóúñü]+'
_PERSON_NAME = rf'{_NAME_TOKEN}(?:\s+{_NAME_TOKEN})?'
_PERSON_PATTERN = re.compile(
    rf'\b(?:'
    rf'[Mm]y\s+(?:friend|brother|sister|mom|dad|mother|father|wife|husband|partner|boss|colleague|coworker)|'
    rf'[Mm]i\s+(?:amig[oa]|herman[oa]|mamá|madre|papá|padre|espos[oa]|pareja|jef[ea]|colega|compañer[oa](?:\s+de\s+trabajo)?)|'
    rf'(?:with|told|asked|met|called|texted|emailed)|'
    rf'(?:con|(?:le\s+)?dije\s+a|pregunté\s+a|conocí\s+a|llamé\s+a|escribí\s+a|hablé\s+con|mensajeé\s+a)'
    rf')\s+({_PERSON_NAME})\b'
)

_RELATIONSHIP_PATTERNS = (
    (re.compile(rf'\b(?:[Mm]y\s+friend|[Mm]i\s+amig[oa])\s+({_PERSON_NAME})\b'), 'friend_of'),
    (re.compile(rf'\b(?:[Mm]y\s+(?:brother|sister)|[Mm]i\s+herman[oa])\s+({_PERSON_NAME})\b'), 'sibling_of'),
    (re.compile(rf'\b(?:[Mm]y\s+(?:mom|dad|mother|father)|[Mm]i\s+(?:mamá|madre|papá|padre))\s+({_PERSON_NAME})\b'), 'parent_of'),
    (re.compile(rf'\b(?:[Mm]y\s+(?:wife|husband)|[Mm]i\s+espos[oa])\s+({_PERSON_NAME})\b'), 'spouse_of'),
    (re.compile(rf'\b(?:[Mm]y\s+partner|[Mm]i\s+pareja)\s+({_PERSON_NAME})\b'), 'partner_of'),
    (re.compile(rf'\b(?:[Mm]y\s+boss|[Mm]i\s+jef[ea])\s+({_PERSON_NAME})\b'), 'reports_to'),
    (re.compile(rf'\b(?:[Mm]y\s+(?:colleague|coworker)|[Mm]i\s+(?:colega|compañer[oa](?:\s+de\s+trabajo)?))\s+({_PERSON_NAME})\b'), 'colleague_of'),
)

_ROMANTIC_PARTNER_PATTERN = re.compile(
    r'\b(?:mi\s+(?:novia|novio|pareja)|amor\s+de\s+mi\s+vida|quiero\s+todo\s+contigo)\b',
    re.IGNORECASE,
)


def _extract_kg_triples(dataset_dir: Path, messages: list[dict]) -> dict:
    """Extract entities and relationships from message content."""
    slug = dataset_dir.name
    entities = set()
    relationships_by_key = {}

    def add_relationship(source: str, target: str, rel_type: str, msg: dict):
        source = source.strip()
        target = target.strip()
        if not source or not target or source.casefold() == target.casefold():
            return
        if source.casefold() != slug.casefold():
            entities.add(source)
        if target.casefold() != slug.casefold():
            entities.add(target)
        key = (source.casefold(), target.casefold(), rel_type)
        relationships_by_key.setdefault(key, {
            'from': source,
            'to': target,
            'type': rel_type,
            'confidence': 'extracted',
            'timestamp': msg.get('timestamp'),
            'source': msg.get('source_file'),
        })

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
        add_relationship(name, slug, 'participant_in', participant_messages[key])

    for assistant_key, assistant_name in assistant_names.items():
        for user_key, user_name in user_names.items():
            if assistant_key != user_key:
                add_relationship(
                    assistant_name,
                    user_name,
                    'communicates_with',
                    participant_messages[user_key],
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
            )

    for msg in messages:
        sender = str(msg.get('metadata', {}).get('sender', '')).strip()
        if msg['role'] != 'assistant':
            continue

        content = msg['content']

        for pattern, rel_type in _RELATIONSHIP_PATTERNS:
            for match in pattern.finditer(content):
                name = match.group(1)
                add_relationship(name, sender or slug, rel_type, msg)

        # General person mentions
        for match in _PERSON_PATTERN.finditer(content):
            entities.add(match.group(1))

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


def _prune_invalid_kg_entities(dataset_dir: Path) -> int:
    """Delete malformed orphan entities left by historical parser failures."""
    db_path = dataset_dir / '.mempalace' / 'palace' / 'knowledge_graph.sqlite3'
    if not db_path.exists():
        return 0
    connection = sqlite3.connect(db_path)
    try:
        cursor = connection.execute(
            "DELETE FROM entities "
            "WHERE (length(name) > 120 OR instr(name, char(10)) > 0 "
            "OR instr(name, char(13)) > 0) "
            "AND id NOT IN (SELECT subject FROM triples) "
            "AND id NOT IN (SELECT object FROM triples)"
        )
        connection.commit()
        return max(cursor.rowcount, 0)
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
                    confidence=1.0,
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
