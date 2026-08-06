#!/usr/bin/env python3
"""
Knowledge Graph query tool for persona-knowledge.

Provides entity lookup, shortest-path search, and statistics
over the persona's relationship graph.

Usage:
    python scripts/query_kg.py --slug sam --entity Tom
    python scripts/query_kg.py --slug sam --path Tom Alice
    python scripts/query_kg.py --slug sam --stats
"""

import argparse
import json
import os
import sys
from collections import defaultdict, deque
from pathlib import Path

KNOWLEDGE_ROOT = Path(os.environ.get(
    'OPENPERSONA_KNOWLEDGE',
    Path.home() / '.openpersona' / 'knowledge'
))


def main():
    parser = argparse.ArgumentParser(description='Query the persona Knowledge Graph')
    parser.add_argument('--slug', required=True, help='Persona dataset slug')
    parser.add_argument('--entity', help='Look up all relationships for an entity')
    parser.add_argument('--path', nargs=2, metavar=('FROM', 'TO'),
                        help='Find shortest path between two entities')
    parser.add_argument('--stats', action='store_true', help='Show KG statistics')
    parser.add_argument('--json', action='store_true', help='Output as JSON')

    args = parser.parse_args()

    dataset_dir = KNOWLEDGE_ROOT / args.slug
    if not dataset_dir.exists():
        print(f'Dataset not found: {dataset_dir}', file=sys.stderr)
        sys.exit(1)

    profiles = _load_participant_profiles(dataset_dir)
    entities, relationships, native_stats = _load_kg(dataset_dir, profiles=profiles)

    if not entities and not relationships:
        print('Knowledge Graph is empty. Ingest data first.', file=sys.stderr)
        sys.exit(1)

    if args.entity:
        _query_entity(
            args.entity,
            entities,
            relationships,
            profiles=profiles,
            as_json=args.json,
        )
    elif args.path:
        _query_path(args.path[0], args.path[1], entities, relationships, as_json=args.json)
    elif args.stats:
        _query_stats(
            entities,
            relationships,
            as_json=args.json,
            native_stats=native_stats,
        )
    else:
        parser.print_help()


def _load_participant_profiles(dataset_dir: Path) -> list[dict]:
    """Load independently identified chat participants."""
    profile_path = dataset_dir / 'participants.json'
    try:
        payload = json.loads(profile_path.read_text(encoding='utf-8'))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []
    profiles = payload.get('participants', [])
    return profiles if isinstance(profiles, list) else []


def _load_kg(
    dataset_dir: Path,
    *,
    profiles: list[dict] | None = None,
) -> tuple[set[str], list[dict], dict | None]:
    """Load entities and relationships from MemPalace KG or fallback JSON."""
    palace_dir = dataset_dir / '.mempalace' / 'palace'

    try:
        from mempalace.knowledge_graph import KnowledgeGraph
        kg = KnowledgeGraph(db_path=str(palace_dir / 'knowledge_graph.sqlite3'))

        all_entities = set()
        all_rels = []
        relationship_keys = set()

        try:
            stats = kg.stats()
            if stats.get('entities', 0):
                all_entities.add(dataset_dir.name)
            query_names = [dataset_dir.name]
            for profile in profiles or _load_participant_profiles(dataset_dir):
                name = str(profile.get('name', '')).strip()
                if name and name.casefold() not in {
                    item.casefold() for item in query_names
                }:
                    query_names.append(name)
                    all_entities.add(name)
            for query_name in query_names:
                result = kg.query_entity(query_name, direction='both')
                if not isinstance(result, list):
                    continue
                for rel in result:
                    source = rel.get('subject', '')
                    target = rel.get('object', '')
                    if source:
                        all_entities.add(source)
                    if target:
                        all_entities.add(target)
                    relationship = {
                        'from': source,
                        'to': target,
                        'type': rel.get('predicate', ''),
                        'confidence': rel.get('confidence'),
                        'source': rel.get('source_closet') or '',
                        'timestamp': rel.get('valid_from'),
                    }
                    key = (
                        relationship['from'],
                        relationship['to'],
                        relationship['type'],
                        relationship['timestamp'],
                    )
                    if key not in relationship_keys:
                        relationship_keys.add(key)
                        all_rels.append(relationship)
        finally:
            kg.close()

        if all_entities:
            return all_entities, all_rels, stats
    except (ImportError, Exception):
        pass

    entities, relationships = _load_kg_fallback(dataset_dir)
    return entities, relationships, None


def _load_kg_fallback(dataset_dir: Path) -> tuple[set[str], list[dict]]:
    """Load from kg-pending.json fallback."""
    kg_file = dataset_dir / '.mempalace' / 'kg-pending.json'
    if not kg_file.exists():
        return set(), []

    try:
        data = json.loads(kg_file.read_text())
    except (json.JSONDecodeError, OSError):
        return set(), []

    entities = set()
    relationships = []

    for entry in data:
        if 'from' in entry and 'to' in entry:
            entities.add(entry['from'])
            entities.add(entry['to'])
            relationships.append(entry)
        elif 'name' in entry:
            entities.add(entry['name'])

    entities.discard('')
    return entities, relationships


def _build_adjacency(relationships: list[dict]) -> dict[str, list[dict]]:
    """Build bidirectional adjacency list from relationships."""
    adj = defaultdict(list)
    for rel in relationships:
        src = rel.get('from', '')
        tgt = rel.get('to', '')
        if src and tgt:
            adj[src].append({'neighbor': tgt, **rel})
            adj[tgt].append({'neighbor': src, **rel})
    return dict(adj)


def _query_entity(
    name: str,
    entities: set[str],
    relationships: list[dict],
    *,
    profiles: list[dict] | None = None,
    as_json: bool,
):
    matched = _fuzzy_match(name, entities)
    if not matched:
        print(f'No entity matching "{name}"', file=sys.stderr)
        sys.exit(1)

    rels = [r for r in relationships
            if r.get('from', '') == matched or r.get('to', '') == matched]

    profile = next(
        (
            item for item in profiles or []
            if str(item.get('name', '')).casefold() == matched.casefold()
        ),
        None,
    )

    if as_json:
        print(json.dumps({'entity': matched, 'profile': profile, 'relationships': rels}, indent=2,
                         ensure_ascii=False))
        return

    print(f'Entity: {matched}')
    if profile:
        print(f'Identity: {profile.get("identity_type", "unknown")}')
        print(f'Messages: {profile.get("message_count", 0)}')
        print(f'Assistant messages: {profile.get("assistant_messages", 0)}')
        print(f'User messages: {profile.get("user_messages", 0)}')
        print(f'First seen: {profile.get("first_seen") or "unknown"}')
        print(f'Last seen: {profile.get("last_seen") or "unknown"}')
    print(f'Relationships: {len(rels)}')
    if not rels:
        print('  (no relationships found)')
        return

    for rel in rels:
        other = rel.get('to') if rel.get('from') == matched else rel.get('from', '?')
        conf = rel.get('confidence', '')
        conf_tag = f' [{conf}]' if conf else ''
        src = rel.get('source', '')
        src_tag = f' (source: {src})' if src else ''
        print(f'  --{rel.get("type", "?")}-->  {other}{conf_tag}{src_tag}')


def _query_path(start: str, end: str, entities: set[str],
                relationships: list[dict], *, as_json: bool):
    start_match = _fuzzy_match(start, entities)
    end_match = _fuzzy_match(end, entities)

    if not start_match:
        print(f'No entity matching "{start}"', file=sys.stderr)
        sys.exit(1)
    if not end_match:
        print(f'No entity matching "{end}"', file=sys.stderr)
        sys.exit(1)
    if start_match == end_match:
        print(f'Start and end resolve to the same entity: {start_match}')
        return

    adj = _build_adjacency(relationships)
    path = _bfs_path(adj, start_match, end_match)

    if as_json:
        print(json.dumps({'from': start_match, 'to': end_match,
                          'path': path, 'hops': len(path) - 1 if path else None},
                         indent=2, ensure_ascii=False))
        return

    if not path:
        print(f'No path found: {start_match} -> {end_match}')
        return

    print(f'Shortest path ({len(path) - 1} hops):')
    for i, node in enumerate(path):
        if i < len(path) - 1:
            edge = _find_edge(relationships, node, path[i + 1])
            rel_type = edge.get('type', '?') if edge else '?'
            conf = edge.get('confidence', '') if edge else ''
            conf_tag = f' [{conf}]' if conf else ''
            print(f'  {node}  --{rel_type}{conf_tag}-->')
        else:
            print(f'  {node}')


def _bfs_path(adj: dict[str, list[dict]], start: str, end: str) -> list[str] | None:
    """BFS shortest path between two entities."""
    if start not in adj or end not in adj:
        return None

    visited = {start}
    queue = deque([(start, [start])])

    while queue:
        current, path = queue.popleft()
        for edge in adj.get(current, []):
            neighbor = edge['neighbor']
            if neighbor == end:
                return path + [neighbor]
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append((neighbor, path + [neighbor]))

    return None


def _find_edge(relationships: list[dict], a: str, b: str) -> dict | None:
    for rel in relationships:
        if (rel.get('from') == a and rel.get('to') == b) or \
           (rel.get('from') == b and rel.get('to') == a):
            return rel
    return None


def _query_stats(
    entities: set[str],
    relationships: list[dict],
    *,
    as_json: bool,
    native_stats: dict | None = None,
):
    type_counts = defaultdict(int)
    confidence_counts = defaultdict(int)
    for rel in relationships:
        type_counts[rel.get('type', 'unknown')] += 1
        confidence_counts[rel.get('confidence', 'untagged')] += 1

    stats = {
        'entities': native_stats.get('entities', len(entities)) if native_stats else len(entities),
        'relationships': native_stats.get('triples', len(relationships)) if native_stats else len(relationships),
        'relationship_types': dict(type_counts),
        'confidence_distribution': dict(confidence_counts),
    }

    if as_json:
        print(json.dumps(stats, indent=2, ensure_ascii=False))
        return

    print(f'Entities: {stats["entities"]}')
    print(f'Relationships: {stats["relationships"]}')
    if type_counts:
        print(f'\nRelationship types:')
        for rtype, count in sorted(type_counts.items(), key=lambda x: -x[1]):
            print(f'  {rtype}: {count}')
    if confidence_counts:
        print(f'\nConfidence distribution:')
        for conf, count in sorted(confidence_counts.items(), key=lambda x: -x[1]):
            print(f'  {conf}: {count}')


def _fuzzy_match(query: str, entities: set[str]) -> str | None:
    """Case-insensitive fuzzy match against entity names."""
    q = query.casefold().strip()
    for entity in entities:
        if entity.casefold() == q:
            return entity
    # Prefer human-style names beginning with the query. This keeps "Abdair"
    # mapped to "Abdair Coca" instead of a dataset slug like "abdair-e2e".
    for entity in sorted(entities, key=str.casefold):
        if entity.casefold().startswith(f'{q} '):
            return entity
    for entity in entities:
        if q in entity.casefold() or entity.casefold() in q:
            return entity
    return None


if __name__ == '__main__':
    main()
