#!/usr/bin/env python3
"""Read-only health report for one persona knowledge dataset."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

from dataset_invariants import build_source_snapshot, validate_dataset
from lint_wiki import lint_wiki
from query_kg import _load_kg, _load_participant_profiles


REQUIRED_EXPORT_PATHS = (
    'raw',
    'conversations.jsonl',
    'profile.md',
    'metadata.json',
    'probes.json',
)


def knowledge_root() -> Path:
    return Path(os.environ.get(
        'OPENPERSONA_KNOWLEDGE',
        Path.home() / '.openpersona' / 'knowledge',
    )).expanduser().resolve()


def _read_json(path: Path) -> dict | None:
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return payload if isinstance(payload, dict) else None


def _git_info(repo_root: Path) -> dict:
    def run(*args: str) -> str | None:
        try:
            result = subprocess.run(
                ['git', *args],
                cwd=repo_root,
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        return result.stdout.strip() if result.returncode == 0 else None

    commit = run('rev-parse', '--short', 'HEAD')
    branch = run('branch', '--show-current')
    status = run('status', '--porcelain')
    return {
        'commit': commit or 'unavailable',
        'branch': branch or 'detached/unavailable',
        'dirty': bool(status) if status is not None else None,
    }


def _participant_health(profiles: list[dict]) -> dict:
    identities = Counter()
    message_count = 0
    assistant_messages = 0
    user_messages = 0
    for profile in profiles:
        if not isinstance(profile, dict):
            continue
        identities[str(profile.get('identity_type') or 'unknown')] += 1
        message_count += int(profile.get('message_count') or 0)
        assistant_messages += int(profile.get('assistant_messages') or 0)
        user_messages += int(profile.get('user_messages') or 0)
    return {
        'profiles': len(profiles),
        'messages': message_count,
        'assistant_messages': assistant_messages,
        'user_messages': user_messages,
        'identity_types': dict(sorted(identities.items())),
    }


def _kg_health(dataset_dir: Path, profiles: list[dict]) -> dict:
    try:
        entities, relationships, _ = _load_kg(dataset_dir, profiles=profiles)
    except (OSError, RuntimeError) as exc:
        return {
            'status': 'error',
            'entities': None,
            'relationships': None,
            'error': str(exc),
        }
    db_path = dataset_dir / '.mempalace' / 'palace' / 'knowledge_graph.sqlite3'
    pending_path = dataset_dir / '.mempalace' / 'kg-pending.json'
    backend = 'sqlite' if db_path.exists() else ('pending_json' if pending_path.exists() else 'none')
    return {
        'status': 'healthy' if backend != 'none' else 'not_built',
        'backend': backend,
        'entities': len(entities),
        'relationships': len(relationships),
    }


def _wiki_health(dataset_dir: Path) -> dict:
    wiki_dir = dataset_dir / 'wiki'
    if not wiki_dir.exists():
        return {
            'status': 'not_built',
            'pages': 0,
            'content_pages': 0,
            'issues': 0,
            'warnings': 0,
        }
    try:
        report = lint_wiki(wiki_dir, dataset_dir)
    except OSError as exc:
        return {
            'status': 'error',
            'pages': None,
            'content_pages': None,
            'issues': 1,
            'warnings': 0,
            'error': str(exc),
        }
    return {
        'status': 'healthy' if not report['issues'] else 'error',
        'pages': report['wiki_pages'],
        'content_pages': report['content_pages'],
        'issues': len(report['issues']),
        'warnings': len(report['warnings']),
    }


def _find_latest_export(
    knowledge_dir: Path,
    slug: str,
    latest_record: dict,
) -> tuple[Path | None, dict | None]:
    configured = os.environ.get('OPENPERSONA_EXPORTS')
    export_root = Path(configured).expanduser() if configured else knowledge_dir.parent / 'exports'
    if not export_root.exists():
        return None, None
    candidates = []
    for candidate in export_root.iterdir():
        if not candidate.is_dir():
            continue
        metadata = _read_json(candidate / 'metadata.json')
        if metadata and metadata.get('slug') == slug:
            candidates.append((candidate, metadata))
    if not candidates:
        return None, None

    expected_version = latest_record.get('version')
    expected_hash = latest_record.get('export_hash')
    matching = [
        item for item in candidates
        if item[1].get('export_version') == expected_version
        and item[1].get('export_hash') == expected_hash
    ]
    pool = matching or candidates
    return max(pool, key=lambda item: item[0].stat().st_mtime)


def _export_health(dataset_dir: Path, dataset_meta: dict, knowledge_dir: Path) -> dict:
    history = dataset_meta.get('export_history', [])
    history = history if isinstance(history, list) else []
    latest_record = history[-1] if history and isinstance(history[-1], dict) else {}
    export_dir, export_metadata = _find_latest_export(
        knowledge_dir,
        dataset_dir.name,
        latest_record,
    )
    current_snapshot = build_source_snapshot(dataset_dir)

    report = {
        'status': 'not_created' if not history else 'recorded',
        'history_entries': len(history),
        'latest_version': latest_record.get('version'),
        'exported_at': latest_record.get('exported_at'),
        'conversation_count': latest_record.get('conversation_count'),
        'artifact_path': str(export_dir) if export_dir else None,
        'missing_paths': [],
    }
    if latest_record and latest_record.get('source_snapshot') != current_snapshot:
        report['status'] = 'stale'

    if export_dir is None:
        return report

    missing = [name for name in REQUIRED_EXPORT_PATHS if not (export_dir / name).exists()]
    report['missing_paths'] = missing
    metadata = export_metadata or _read_json(export_dir / 'metadata.json')
    if missing or metadata is None:
        report['status'] = 'error'
        return report

    conversations = export_dir / 'conversations.jsonl'
    actual_hash = 'sha256:' + hashlib.sha256(conversations.read_bytes()).hexdigest()[:16]
    expected_hash = metadata.get('export_hash')
    report['hash_matches'] = expected_hash == actual_hash
    report['snapshot_matches'] = metadata.get('source_snapshot') == current_snapshot
    if not report['hash_matches'] or not report['snapshot_matches']:
        report['status'] = 'stale' if report['hash_matches'] else 'error'
    elif latest_record and metadata.get('export_version') != latest_record.get('version'):
        report['status'] = 'stale'
    else:
        report['status'] = 'healthy'
    return report


def build_diagnosis(dataset_dir: Path, *, repo_root: Path | None = None) -> dict:
    """Collect a deterministic report without changing dataset files."""
    dataset_dir = dataset_dir.resolve()
    if not dataset_dir.exists():
        raise FileNotFoundError(f'Dataset not found: {dataset_dir}')

    metadata = _read_json(dataset_dir / 'dataset.json') or {}
    profiles = _load_participant_profiles(dataset_dir)
    invariants = validate_dataset(dataset_dir)
    kg = _kg_health(dataset_dir, profiles)
    wiki = _wiki_health(dataset_dir)
    export = _export_health(dataset_dir, metadata, dataset_dir.parent)
    repo_root = repo_root or Path(__file__).resolve().parent.parent

    critical_errors = list(invariants['errors'])
    if kg['status'] == 'error':
        critical_errors.append({'check': 'kg.health', 'actual': kg.get('error', 'error')})
    if wiki['status'] == 'error':
        critical_errors.append({'check': 'wiki.health', 'actual': wiki.get('error', 'issues')})
    if export['status'] == 'error':
        critical_errors.append({'check': 'export.health', 'actual': 'error'})

    warnings = list(invariants['warnings'])
    for component, component_report in (('kg', kg), ('wiki', wiki), ('export', export)):
        if component_report['status'] in {'not_built', 'not_created', 'stale'}:
            warnings.append({'check': f'{component}.health', 'status': component_report['status']})

    return {
        'ok': not critical_errors,
        'status': 'healthy' if not critical_errors and not warnings else (
            'warning' if not critical_errors else 'error'
        ),
        'knowledge_root': str(dataset_dir.parent),
        'dataset_path': str(dataset_dir),
        'slug': metadata.get('slug', dataset_dir.name),
        'name': metadata.get('name'),
        'git': _git_info(repo_root),
        'schema_version': metadata.get('schema_version'),
        'sources': {
            'files': invariants['counts']['source_files'],
            'messages': invariants['counts']['messages'],
            'assistant_turns': invariants['counts']['assistant_turns'],
        },
        'participants': _participant_health(profiles),
        'vectors': {
            'count': invariants['counts']['vectors'],
            'status': 'healthy' if not any(
                error['check'] == 'vectors.count' for error in invariants['errors']
            ) else 'error',
        },
        'kg': kg,
        'wiki': wiki,
        'export': export,
        'invariants': {
            'ok': invariants['ok'],
            'errors': invariants['errors'],
            'warnings': invariants['warnings'],
        },
        'errors': critical_errors,
        'warnings': warnings,
    }


def print_report(report: dict) -> None:
    git = report['git']
    sources = report['sources']
    participants = report['participants']
    vectors = report['vectors']
    kg = report['kg']
    wiki = report['wiki']
    export = report['export']
    dirty = 'dirty' if git['dirty'] else ('clean' if git['dirty'] is False else 'unknown')

    print(f'Dataset diagnosis: {report["slug"]} [{report["status"]}]')
    print(f'  Knowledge root: {report["knowledge_root"]}')
    print(f'  Dataset path: {report["dataset_path"]}')
    print(f'  Git: {git["commit"]} ({git["branch"]}, {dirty})')
    print(f'  Schema: {report["schema_version"]}')
    print(
        f'  Sources: {sources["files"]} files, {sources["messages"]} messages, '
        f'{sources["assistant_turns"]} assistant turns'
    )
    identity_types = ', '.join(
        f'{name}={count}' for name, count in participants['identity_types'].items()
    ) or 'none'
    print(
        f'  Participants: {participants["profiles"]} profiles, '
        f'{participants["messages"]} messages ({identity_types})'
    )
    print(f'  Vectors: {vectors["count"]} [{vectors["status"]}]')
    print(
        f'  KG: {kg["entities"]} entities, {kg["relationships"]} relationships '
        f'[{kg["status"]}]'
    )
    print(
        f'  Wiki: {wiki["content_pages"]}/{wiki["pages"]} content/total pages, '
        f'{wiki["issues"]} issues, {wiki["warnings"]} warnings [{wiki["status"]}]'
    )
    print(
        f'  Export: {export["history_entries"]} records, '
        f'latest={export["latest_version"] or "none"}, '
        f'turns={export["conversation_count"] if export["conversation_count"] is not None else "n/a"} '
        f'[{export["status"]}]'
    )
    print(
        f'  Invariants: {len(report["errors"])} errors, '
        f'{len(report["warnings"])} warnings'
    )


def main() -> None:
    parser = argparse.ArgumentParser(description='Diagnose all persisted dataset layers')
    parser.add_argument('--slug', required=True, help='Persona dataset slug')
    parser.add_argument('--json', action='store_true', help='Output machine-readable JSON')
    args = parser.parse_args()

    dataset_dir = knowledge_root() / args.slug
    try:
        report = build_diagnosis(dataset_dir)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print_report(report)
    raise SystemExit(0 if report['ok'] else 1)


if __name__ == '__main__':
    main()
