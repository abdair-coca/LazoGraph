#!/usr/bin/env python3
"""Read-only post-rebuild smoke tests across searchable dataset layers."""

import argparse
import json
import os
import sys
from pathlib import Path

from diagnose import _find_latest_export, _read_json
from lint_wiki import lint_wiki
from query_kg import _bfs_path, _build_adjacency, _load_kg, _load_participant_profiles, _resolve_entity
from query_memory import _resolve_participant, search_memory


def knowledge_root() -> Path:
    return Path(os.environ.get(
        'OPENPERSONA_KNOWLEDGE',
        Path.home() / '.openpersona' / 'knowledge',
    )).expanduser().resolve()


def _check(name: str, callback) -> dict:
    try:
        detail = callback()
    except Exception as exc:
        return {'name': name, 'status': 'failed', 'detail': str(exc)}
    return {'name': name, 'status': 'passed', 'detail': detail}


def _aliases(dataset_dir: Path, profiles: list[dict]) -> str:
    checked = 0
    for profile in profiles:
        canonical = str(profile.get('name', '')).strip()
        if not canonical:
            raise AssertionError('Participant has no canonical name')
        for alias in {canonical, *map(str, profile.get('aliases', []))}:
            resolved = _resolve_participant(dataset_dir, alias)
            if resolved != canonical:
                raise AssertionError(f'Alias {alias!r} resolved to {resolved!r}, expected {canonical!r}')
            checked += 1
    if not checked:
        raise AssertionError('No participant identities available')
    return f'{checked} canonical names/aliases resolved'


def _kg_paths(dataset_dir: Path, profiles: list[dict]) -> str:
    entities, relationships, _ = _load_kg(dataset_dir, profiles=profiles)
    personas = [profile for profile in profiles if profile.get('identity_type') == 'persona']
    contacts = [profile for profile in profiles if profile.get('identity_type') == 'contact']
    if not personas or not contacts:
        raise AssertionError('KG path smoke test requires one persona and one contact')
    persona = _resolve_entity(str(personas[0].get('name', '')), entities, profiles)
    if not persona:
        raise AssertionError('Persona does not resolve to a KG entity')
    adjacency = _build_adjacency(relationships)
    checked = 0
    for contact_profile in contacts:
        contact = _resolve_entity(str(contact_profile.get('name', '')), entities, profiles)
        if contact and _bfs_path(adjacency, persona, contact):
            checked += 1
    if not checked:
        raise AssertionError('No KG path connects persona to any contact')
    return f'{checked}/{len(contacts)} contacts connected to persona'


def _semantic_search(dataset_dir: Path, profiles: list[dict]) -> str:
    checked = 0
    for profile in profiles:
        if int(profile.get('message_count') or 0) < 1:
            continue
        participant = str(profile.get('name', '')).strip()
        results = search_memory(dataset_dir, 'conversation', participant=participant, limit=1)
        if not results:
            raise AssertionError(f'No semantic result for {participant}')
        sender = str(results[0].get('metadata', {}).get('sender', '')).strip()
        if sender != participant:
            raise AssertionError(
                f'Semantic filter for {participant!r} returned sender {sender!r}'
            )
        checked += 1
    if not checked:
        raise AssertionError('No participants with messages available')
    return f'{checked} participant filters returned canonical sender'


def _wiki(dataset_dir: Path) -> str:
    wiki_dir = dataset_dir / 'wiki'
    if not wiki_dir.exists():
        raise AssertionError('Wiki not built')
    report = lint_wiki(wiki_dir, dataset_dir)
    if report['issues']:
        raise AssertionError(f'{len(report["issues"])} wiki lint issues')
    return f'{report["content_pages"]} content pages, {len(report["warnings"])} warnings'


def _export_pairs(dataset_dir: Path, export_dir: Path | None = None) -> str:
    metadata = _read_json(dataset_dir / 'dataset.json') or {}
    history = metadata.get('export_history', [])
    latest = history[-1] if history and isinstance(history[-1], dict) else {}
    if export_dir is None:
        export_dir, _ = _find_latest_export(dataset_dir.parent, dataset_dir.name, latest)
    if export_dir is None:
        return 'skipped: no export artifact'
    path = export_dir / 'conversations.jsonl'
    try:
        turns = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line]
    except (OSError, json.JSONDecodeError) as exc:
        raise AssertionError(f'Export conversations unreadable: {exc}') from exc
    if not turns:
        raise AssertionError('Export contains no conversation turns')
    if len(turns) % 2:
        raise AssertionError(f'Export has odd turn count: {len(turns)}')
    for index in range(0, len(turns), 2):
        if turns[index].get('role') != 'user' or turns[index + 1].get('role') != 'assistant':
            raise AssertionError(f'Broken user/assistant pair at turn {index + 1}')
    return f'{len(turns) // 2} complete user/assistant pairs'


def run_smoke_tests(dataset_dir: Path, *, export_dir: Path | None = None) -> dict:
    """Run cross-layer probes and return all failures instead of stopping at first."""
    dataset_dir = dataset_dir.resolve()
    profiles = _load_participant_profiles(dataset_dir)
    checks = [
        _check('canonical-aliases', lambda: _aliases(dataset_dir, profiles)),
        _check('kg-paths', lambda: _kg_paths(dataset_dir, profiles)),
        _check('participant-semantic-search', lambda: _semantic_search(dataset_dir, profiles)),
        _check('wiki-lint', lambda: _wiki(dataset_dir)),
        _check('export-pair-balance', lambda: _export_pairs(dataset_dir, export_dir)),
    ]
    return {
        'ok': all(check['status'] == 'passed' for check in checks),
        'slug': dataset_dir.name,
        'checks': checks,
    }


def print_report(report: dict) -> None:
    print(f'Post-rebuild smoke tests: {report["slug"]}')
    for check in report['checks']:
        print(f'  {check["status"].upper():6s} {check["name"]}: {check["detail"]}')
    passed = sum(check['status'] == 'passed' for check in report['checks'])
    print(f'  Result: {passed}/{len(report["checks"])} passed')


def main() -> None:
    parser = argparse.ArgumentParser(description='Run post-rebuild dataset smoke tests')
    parser.add_argument('--slug', required=True, help='Persona dataset slug')
    parser.add_argument('--export', type=Path, help='Explicit export directory')
    parser.add_argument('--json', action='store_true', help='Output machine-readable JSON')
    args = parser.parse_args()
    dataset_dir = knowledge_root() / args.slug
    if not dataset_dir.exists():
        print(f'Dataset not found: {dataset_dir}', file=sys.stderr)
        raise SystemExit(1)
    report = run_smoke_tests(
        dataset_dir,
        export_dir=args.export.expanduser().resolve() if args.export else None,
    )
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print_report(report)
    raise SystemExit(0 if report['ok'] else 1)


if __name__ == '__main__':
    main()
