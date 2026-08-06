#!/usr/bin/env python3
"""Semantic search over MemPalace with canonical participant filtering."""

import argparse
import json
import os
import sys
from pathlib import Path

KNOWLEDGE_ROOT = Path(os.environ.get(
    'OPENPERSONA_KNOWLEDGE',
    Path.home() / '.openpersona' / 'knowledge',
))


def main():
    parser = argparse.ArgumentParser(description='Search persona memories semantically')
    parser.add_argument('--slug', required=True, help='Persona dataset slug')
    parser.add_argument('--query', required=True, help='Natural-language semantic query')
    parser.add_argument('--participant', help='Canonical participant name or recognized alias')
    parser.add_argument('--limit', type=int, default=5, help='Maximum results (default: 5)')
    parser.add_argument('--json', action='store_true', help='Output as JSON')
    args = parser.parse_args()

    dataset_dir = KNOWLEDGE_ROOT / args.slug
    if not dataset_dir.exists():
        print(f'Dataset not found: {dataset_dir}', file=sys.stderr)
        sys.exit(1)
    if args.limit < 1:
        parser.error('--limit must be at least 1')

    participant = None
    if args.participant:
        participant = _resolve_participant(dataset_dir, args.participant)
        if not participant:
            print(f'No participant matching "{args.participant}"', file=sys.stderr)
            sys.exit(1)

    results = search_memory(
        dataset_dir,
        args.query,
        participant=participant,
        limit=args.limit,
    )
    if not results:
        print('No semantic results found.', file=sys.stderr)
        sys.exit(1)
    if args.json:
        print(json.dumps({'query': args.query, 'participant': participant, 'results': results},
                         indent=2, ensure_ascii=False))
        return

    label = f' for {participant}' if participant else ''
    print(f'Semantic results{label}: {len(results)}')
    for index, result in enumerate(results, 1):
        metadata = result['metadata']
        timestamp = metadata.get('authored_at') or 'unknown time'
        sender = metadata.get('sender') or 'unknown sender'
        distance = result.get('distance')
        distance_text = f'{distance:.4f}' if isinstance(distance, (int, float)) else 'unknown'
        content = result['content'].replace('\n', ' ')
        print(f'  {index}. [{sender}, {timestamp}, distance={distance_text}] {content}')


def _load_profiles(dataset_dir: Path) -> list[dict]:
    try:
        payload = json.loads((dataset_dir / 'participants.json').read_text(encoding='utf-8'))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []
    profiles = payload.get('participants', [])
    return profiles if isinstance(profiles, list) else []


def _resolve_participant(dataset_dir: Path, query: str) -> str | None:
    normalized = query.casefold().strip()
    profiles = _load_profiles(dataset_dir)
    for profile in profiles:
        name = str(profile.get('name', '')).strip()
        aliases = [name, *profile.get('aliases', [])]
        if any(str(alias).casefold().strip() == normalized for alias in aliases):
            return name
    for profile in profiles:
        name = str(profile.get('name', '')).strip()
        if normalized in name.casefold() or name.casefold() in normalized:
            return name
    return None


def search_memory(
    dataset_dir: Path,
    query: str,
    *,
    participant: str | None = None,
    limit: int = 5,
) -> list[dict]:
    from mempalace.palace import get_collection

    collection = get_collection(
        str(dataset_dir / '.mempalace' / 'palace'),
        create=False,
    )
    where = {'wing': dataset_dir.name}
    if participant:
        where = {'$and': [where, {'sender': participant}]}
    result = collection.query(
        query_texts=[query],
        n_results=limit,
        where=where,
        include=['documents', 'metadatas', 'distances'],
    )
    documents = (result.get('documents') or [[]])[0]
    metadatas = (result.get('metadatas') or [[]])[0]
    distances = (result.get('distances') or [[]])[0]
    ids = (result.get('ids') or [[]])[0]
    return [
        {
            'id': ids[index] if index < len(ids) else None,
            'content': document,
            'metadata': metadatas[index] if index < len(metadatas) else {},
            'distance': distances[index] if index < len(distances) else None,
        }
        for index, document in enumerate(documents)
    ]


if __name__ == '__main__':
    main()
