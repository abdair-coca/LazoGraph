#!/usr/bin/env python3
"""Run a disposable end-to-end verification from raw source to training export."""

import argparse
import gc
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from runtime import configure_safe_output

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
CONTENT_PAGES = ('identity', 'voice', 'values', 'thinking', 'relationships', 'timeline')


def main():
    configure_safe_output()
    parser = argparse.ArgumentParser(description='Run disposable LazoGraph end-to-end test')
    parser.add_argument('--source', required=True, help='Raw source file or directory')
    parser.add_argument('--persona-name', required=True, help='Persona name used for role detection')
    parser.add_argument('--persona-query', help='Entity query expected to resolve to persona')
    parser.add_argument('--contact-query', help='Entity or alias query expected to resolve to contact')
    parser.add_argument('--expect-messages', type=int)
    parser.add_argument('--expect-persona-messages', type=int)
    parser.add_argument('--expect-contact-messages', type=int)
    parser.add_argument(
        '--stage-timeout',
        type=int,
        default=900,
        help='Maximum seconds per subprocess stage (default: 900)',
    )
    parser.add_argument(
        '--keep-temp',
        action='store_true',
        help='Preserve disposable data for debugging',
    )
    args = parser.parse_args()
    if args.stage_timeout < 1:
        parser.error('--stage-timeout must be at least 1 second')

    source = Path(args.source).expanduser().resolve()
    if not source.exists():
        print(f'Source not found: {source}', file=sys.stderr)
        sys.exit(1)

    root = Path(tempfile.mkdtemp(prefix='LazoGraph-e2e-'))
    summary = None
    try:
        knowledge_root = root / 'knowledge'
        export_dir = root / 'training'
        slug = 'lazograph-e2e'
        env = os.environ.copy()
        env['PYTHONUTF8'] = '1'
        env['PYTHONUNBUFFERED'] = '1'
        env['OPENPERSONA_KNOWLEDGE'] = str(knowledge_root)

        def run(label: str, script: str, *arguments: str):
            _run(
                label,
                script,
                *arguments,
                env=env,
                timeout=args.stage_timeout,
            )

        run('initialize', 'init_knowledge.py', '--slug', slug, '--name', args.persona_name)
        run(
            'parse dry-run',
            'ingest.py',
            '--slug', slug,
            '--source', str(source),
            '--persona-name', args.persona_name,
            '--dry-run',
        )
        run(
            'ingest',
            'ingest.py',
            '--slug', slug,
            '--source', str(source),
            '--persona-name', args.persona_name,
        )
        run('rebuild KG', 'ingest.py', '--slug', slug, '--rebuild-kg')
        run('analyze wiki dry-run', 'build_wiki.py', '--slug', slug, '--dry-run')
        run('build wiki', 'build_wiki.py', '--slug', slug)
        run('lint wiki', 'lint_wiki.py', '--slug', slug)
        if args.persona_query:
            run('query persona', 'query_kg.py', '--slug', slug, '--entity', args.persona_query)
        if args.contact_query:
            run('query contact', 'query_kg.py', '--slug', slug, '--entity', args.contact_query)
        if args.persona_query and args.contact_query:
            run(
                'query path',
                'query_kg.py',
                '--slug', slug,
                '--path', args.persona_query, args.contact_query,
            )
        if args.persona_query:
            run(
                'semantic query persona',
                'query_memory.py',
                '--slug', slug,
                '--query', 'trabajo y proyectos',
                '--participant', args.persona_query,
                '--limit', '1',
            )
        if args.contact_query:
            run(
                'semantic query contact',
                'query_memory.py',
                '--slug', slug,
                '--query', 'conversación cotidiana',
                '--participant', args.contact_query,
                '--limit', '1',
            )
        run('export', 'export_training.py', '--slug', slug, '--output', str(export_dir))

        summary = _validate(
            knowledge_root / slug,
            export_dir,
            expect_messages=args.expect_messages,
            expect_persona_messages=args.expect_persona_messages,
            expect_contact_messages=args.expect_contact_messages,
        )
    finally:
        if args.keep_temp:
            print(f'\nTemporary data preserved: {root}', flush=True)
        else:
            _cleanup_with_retries(root)

    print('\nE2E: PASS')
    print(f'  messages: {summary["messages"]}')
    print(f'  vectors: {summary["vectors"]}')
    print(f'  participants: {summary["participants"]}')
    print(f'  KG relationships: {summary["relationships"]}')
    print(f'  wiki pages: {summary["wiki_pages"]}')
    print(f'  export turns: {summary["export_turns"]}')
    print('  temporary data: removed')


def _run(label: str, script: str, *arguments: str, env: dict, timeout: int = 900):
    print(f'\n[{label}]', flush=True)
    command = [sys.executable, '-u', str(SCRIPT_DIR / script), *arguments]
    try:
        subprocess.run(
            command,
            cwd=PROJECT_DIR,
            env=env,
            check=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f'Stage {label!r} exceeded {timeout} seconds: {" ".join(command)}'
        ) from exc


def _cleanup_with_retries(path: Path, *, attempts: int = 4) -> None:
    """Remove disposable E2E state, tolerating briefly held Windows SQLite files."""
    last_error = None
    for attempt in range(attempts):
        gc.collect()
        try:
            shutil.rmtree(path)
            return
        except FileNotFoundError:
            return
        except PermissionError as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(0.25 * (2 ** attempt))
    raise RuntimeError(f'Could not remove temporary E2E data after {attempts} attempts: {path}') from last_error


def _validate(
    dataset_dir: Path,
    export_dir: Path,
    *,
    expect_messages: int | None,
    expect_persona_messages: int | None,
    expect_contact_messages: int | None,
) -> dict:
    metadata = json.loads((dataset_dir / 'dataset.json').read_text(encoding='utf-8'))
    profiles = json.loads(
        (dataset_dir / 'participants.json').read_text(encoding='utf-8')
    )['participants']
    personas = [profile for profile in profiles if profile['identity_type'] == 'persona']
    contacts = [profile for profile in profiles if profile['identity_type'] == 'contact']
    if len(personas) != 1 or not contacts:
        raise AssertionError('Expected one persona and at least one independent contact')

    messages = metadata['stats']['total_messages']
    if expect_messages is not None and messages != expect_messages:
        raise AssertionError(f'Expected {expect_messages} messages, found {messages}')
    if expect_persona_messages is not None and personas[0]['message_count'] != expect_persona_messages:
        raise AssertionError(
            f'Expected {expect_persona_messages} persona messages, '
            f'found {personas[0]["message_count"]}'
        )
    contact_messages = sum(profile['message_count'] for profile in contacts)
    if expect_contact_messages is not None and contact_messages != expect_contact_messages:
        raise AssertionError(
            f'Expected {expect_contact_messages} contact messages, found {contact_messages}'
        )
    if sum(profile['message_count'] for profile in profiles) != messages:
        raise AssertionError('Participant totals do not match dataset message count')

    chroma_path = dataset_dir / '.mempalace' / 'palace' / 'chroma.sqlite3'
    connection = sqlite3.connect(chroma_path)
    try:
        vectors = connection.execute('SELECT COUNT(*) FROM embeddings').fetchone()[0]
    finally:
        connection.close()
    if vectors != messages:
        raise AssertionError(f'Expected {messages} vectors, found {vectors}')

    kg_path = dataset_dir / '.mempalace' / 'palace' / 'knowledge_graph.sqlite3'
    connection = sqlite3.connect(kg_path)
    try:
        relationships = connection.execute('SELECT COUNT(*) FROM triples').fetchone()[0]
    finally:
        connection.close()
    if relationships < 3:
        raise AssertionError(f'Expected at least 3 KG relationships, found {relationships}')

    for page_name in CONTENT_PAGES:
        page = (dataset_dir / 'wiki' / f'{page_name}.md').read_text(encoding='utf-8')
        if '(awaiting' in page or page.count('[L') < 2:
            raise AssertionError(f'Wiki page is not populated: {page_name}')

    conversations = [
        json.loads(line)
        for line in (export_dir / 'conversations.jsonl').read_text(encoding='utf-8').splitlines()
    ]
    if not conversations:
        raise AssertionError('Training export has no conversations')
    if any(turn.get('content') == 'Go on.' for turn in conversations):
        raise AssertionError('Training export contains invented Go on. prompts')
    if {turn.get('role') for turn in conversations} != {'user', 'assistant'}:
        raise AssertionError('Training export does not contain both roles')
    if len(conversations) % 2 or any(
        conversations[index].get('role') != 'user'
        or conversations[index + 1].get('role') != 'assistant'
        for index in range(0, len(conversations), 2)
    ):
        raise AssertionError('Training export does not contain complete user/assistant pairs')
    for required in ('profile.md', 'metadata.json', 'probes.json'):
        if not (export_dir / required).exists():
            raise AssertionError(f'Missing export artifact: {required}')

    return {
        'messages': messages,
        'vectors': vectors,
        'participants': [(profile['name'], profile['message_count']) for profile in profiles],
        'relationships': relationships,
        'wiki_pages': len(CONTENT_PAGES),
        'export_turns': len(conversations),
    }


if __name__ == '__main__':
    main()
