#!/usr/bin/env python3
"""Coordinate vector, KG, and wiki rebuilds with optional filesystem rollback."""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
KNOWLEDGE_ROOT = Path(os.environ.get(
    'OPENPERSONA_KNOWLEDGE',
    Path.home() / '.openpersona' / 'knowledge',
))
AFFECTED_PATHS = (
    Path('.mempalace') / 'palace',
    Path('participants.json'),
    Path('dataset.json'),
    Path('wiki'),
)


def main():
    parser = argparse.ArgumentParser(
        description='Rebuild vectors, KG, and wiki as one coordinated workflow'
    )
    parser.add_argument('--slug', required=True, help='Persona dataset slug')
    parser.add_argument(
        '--atomic',
        action='store_true',
        help='Snapshot affected layers and restore them if any stage fails',
    )
    args = parser.parse_args()

    dataset_dir = KNOWLEDGE_ROOT / args.slug
    if not dataset_dir.exists():
        print(f'Dataset not found: {dataset_dir}', file=sys.stderr)
        sys.exit(1)

    try:
        result = rebuild_dataset(dataset_dir, args.slug, atomic=args.atomic)
    except KeyboardInterrupt:
        print('Rebuild interrupted; rollback attempted.', file=sys.stderr)
        sys.exit(130)
    except Exception as exc:
        print(f'Rebuild failed: {exc}', file=sys.stderr)
        sys.exit(1)

    mode = 'atomic' if args.atomic else 'non-atomic'
    print(f'\n✅ Combined rebuild complete ({mode}): {len(result["stages"])} stages')


def rebuild_dataset(
    dataset_dir: Path,
    slug: str,
    *,
    atomic: bool = False,
    runner=None,
) -> dict:
    """Run every rebuild stage; restore exact prior state on atomic failure."""
    dataset_dir = dataset_dir.resolve()
    if not dataset_dir.is_dir():
        raise RuntimeError(f'Dataset directory not found: {dataset_dir}')
    runner = runner or _run_stage
    stages = _build_stages(slug)

    with _dataset_lock(dataset_dir):
        if not atomic:
            _execute_stages(stages, runner, dataset_dir)
            return {'stages': [stage['name'] for stage in stages], 'rolled_back': False}

        with tempfile.TemporaryDirectory(prefix='LazoGraph-rebuild-') as temp:
            backup_dir = Path(temp) / 'snapshot'
            manifest = _snapshot_state(dataset_dir, backup_dir)
            print(f'Atomic snapshot ready: {len(manifest)} managed paths')
            try:
                _execute_stages(stages, runner, dataset_dir)
            except BaseException:
                _restore_state(dataset_dir, backup_dir, manifest)
                print('Rollback complete: previous dataset state restored.', file=sys.stderr)
                raise

    return {'stages': [stage['name'] for stage in stages], 'rolled_back': False}


def _build_stages(slug: str) -> list[dict]:
    return [
        {
            'name': 'vectors',
            'script': 'ingest.py',
            'arguments': ('--slug', slug, '--rebuild-vectors'),
        },
        {
            'name': 'knowledge-graph',
            'script': 'ingest.py',
            'arguments': ('--slug', slug, '--rebuild-kg'),
        },
        {
            'name': 'wiki',
            'script': 'build_wiki.py',
            'arguments': ('--slug', slug),
        },
        {
            'name': 'wiki-lint',
            'script': 'lint_wiki.py',
            'arguments': ('--slug', slug),
        },
        {
            'name': 'smoke-tests',
            'script': 'smoke_test.py',
            'arguments': ('--slug', slug),
        },
    ]


def _execute_stages(stages: list[dict], runner, dataset_dir: Path):
    for index, stage in enumerate(stages, 1):
        print(f'\n[{index}/{len(stages)}] {stage["name"]}', flush=True)
        runner(stage, dataset_dir)


def _run_stage(stage: dict, dataset_dir: Path):
    env = os.environ.copy()
    env['OPENPERSONA_KNOWLEDGE'] = str(dataset_dir.parent)
    env['PYTHONUTF8'] = '1'
    env['PYTHONUNBUFFERED'] = '1'
    subprocess.run(
        [
            sys.executable,
            str(SCRIPT_DIR / stage['script']),
            *stage['arguments'],
        ],
        cwd=PROJECT_DIR,
        env=env,
        check=True,
    )


@contextmanager
def _dataset_lock(dataset_dir: Path):
    lock_path = dataset_dir / '.rebuild.lock'
    payload = {
        'pid': os.getpid(),
        'started_at': datetime.now(timezone.utc).isoformat(),
    }
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise RuntimeError(
            f'Rebuild already in progress or stale lock exists: {lock_path}'
        ) from exc
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as lock:
            json.dump(payload, lock)
        yield
    finally:
        lock_path.unlink(missing_ok=True)


def _snapshot_state(dataset_dir: Path, backup_dir: Path) -> dict[str, str]:
    backup_dir.mkdir(parents=True)
    manifest = {}
    for relative in AFFECTED_PATHS:
        source = _safe_target(dataset_dir, relative)
        destination = backup_dir / relative
        if source.is_dir():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source, destination)
            manifest[str(relative)] = 'directory'
        elif source.is_file():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            manifest[str(relative)] = 'file'
        else:
            manifest[str(relative)] = 'missing'
    return manifest


def _restore_state(dataset_dir: Path, backup_dir: Path, manifest: dict[str, str]):
    for relative in AFFECTED_PATHS:
        relative_key = str(relative)
        target = _safe_target(dataset_dir, relative)
        _remove_managed_target(target)
        original_type = manifest.get(relative_key, 'missing')
        backup = backup_dir / relative
        if original_type == 'directory':
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(backup, target)
        elif original_type == 'file':
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup, target)


def _safe_target(dataset_dir: Path, relative: Path) -> Path:
    if relative not in AFFECTED_PATHS:
        raise RuntimeError(f'Unmanaged rollback target rejected: {relative}')
    dataset_root = dataset_dir.resolve()
    target = dataset_dir / relative
    resolved = target.resolve(strict=False)
    try:
        resolved.relative_to(dataset_root)
    except ValueError as exc:
        raise RuntimeError(f'Rollback target escapes dataset: {target}') from exc
    return target


def _remove_managed_target(target: Path):
    if target.is_symlink() or target.is_file():
        target.unlink(missing_ok=True)
    elif target.is_dir():
        shutil.rmtree(target)


if __name__ == '__main__':
    main()
