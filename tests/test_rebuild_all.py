#!/usr/bin/env python3
"""Tests for coordinated rebuild snapshot and rollback behavior."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import rebuild_all


class TestAtomicRebuild(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dataset = Path(self.tmp.name) / 'sam'
        self.palace = self.dataset / '.mempalace' / 'palace'
        self.wiki = self.dataset / 'wiki'
        self.palace.mkdir(parents=True)
        self.wiki.mkdir(parents=True)
        self.palace.joinpath('chroma.sqlite3').write_bytes(b'old-vectors')
        self.palace.joinpath('knowledge_graph.sqlite3').write_bytes(b'old-kg')
        self.dataset.joinpath('participants.json').write_text('old-participants')
        self.dataset.joinpath('dataset.json').write_text('old-dataset')
        self.wiki.joinpath('identity.md').write_text('old-wiki')

    def tearDown(self):
        self.tmp.cleanup()

    def _mutating_runner(self, *, fail_on: str | None = None, interrupt=False, calls=None):
        def runner(stage, _dataset_dir):
            if calls is not None:
                calls.append(stage['name'])
            if stage['name'] == 'vectors':
                self.palace.joinpath('chroma.sqlite3').write_bytes(b'new-vectors')
                self.palace.joinpath('new-segment.bin').write_bytes(b'new-segment')
                self.dataset.joinpath('participants.json').write_text('new-participants')
            elif stage['name'] == 'knowledge-graph':
                self.palace.joinpath('knowledge_graph.sqlite3').write_bytes(b'new-kg')
                self.dataset.joinpath('dataset.json').write_text('new-dataset')
            elif stage['name'] == 'wiki':
                self.wiki.joinpath('identity.md').write_text('new-wiki')
                self.wiki.joinpath('new-page.md').write_text('new-page')
            if stage['name'] == fail_on:
                if interrupt:
                    raise KeyboardInterrupt()
                raise RuntimeError(f'{fail_on} failed')
        return runner

    def _assert_old_state(self):
        self.assertEqual(self.palace.joinpath('chroma.sqlite3').read_bytes(), b'old-vectors')
        self.assertEqual(
            self.palace.joinpath('knowledge_graph.sqlite3').read_bytes(),
            b'old-kg',
        )
        self.assertFalse(self.palace.joinpath('new-segment.bin').exists())
        self.assertEqual(self.dataset.joinpath('participants.json').read_text(), 'old-participants')
        self.assertEqual(self.dataset.joinpath('dataset.json').read_text(), 'old-dataset')
        self.assertEqual(self.wiki.joinpath('identity.md').read_text(), 'old-wiki')
        self.assertFalse(self.wiki.joinpath('new-page.md').exists())
        self.assertFalse(self.dataset.joinpath('.rebuild.lock').exists())

    def test_atomic_success_keeps_new_state_and_runs_all_stages(self):
        calls = []

        result = rebuild_all.rebuild_dataset(
            self.dataset,
            'sam',
            atomic=True,
            runner=self._mutating_runner(calls=calls),
        )

        self.assertEqual(calls, ['vectors', 'knowledge-graph', 'wiki', 'wiki-lint'])
        self.assertFalse(result['rolled_back'])
        self.assertEqual(self.palace.joinpath('chroma.sqlite3').read_bytes(), b'new-vectors')
        self.assertEqual(self.dataset.joinpath('dataset.json').read_text(), 'new-dataset')
        self.assertEqual(self.wiki.joinpath('identity.md').read_text(), 'new-wiki')
        self.assertFalse(self.dataset.joinpath('.rebuild.lock').exists())

    def test_atomic_failure_restores_exact_old_state(self):
        with self.assertRaisesRegex(RuntimeError, 'wiki failed'):
            rebuild_all.rebuild_dataset(
                self.dataset,
                'sam',
                atomic=True,
                runner=self._mutating_runner(fail_on='wiki'),
            )

        self._assert_old_state()

    def test_keyboard_interrupt_also_rolls_back(self):
        with self.assertRaises(KeyboardInterrupt):
            rebuild_all.rebuild_dataset(
                self.dataset,
                'sam',
                atomic=True,
                runner=self._mutating_runner(fail_on='knowledge-graph', interrupt=True),
            )

        self._assert_old_state()

    def test_paths_missing_before_transaction_are_removed_on_rollback(self):
        shutil.rmtree(self.dataset / '.mempalace')
        shutil.rmtree(self.wiki)
        self.dataset.joinpath('participants.json').unlink()

        def create_then_fail(_stage, _dataset_dir):
            self.palace.mkdir(parents=True, exist_ok=True)
            self.palace.joinpath('created.db').write_bytes(b'created')
            self.wiki.mkdir()
            self.wiki.joinpath('created.md').write_text('created')
            self.dataset.joinpath('participants.json').write_text('created')
            raise RuntimeError('stop')

        with self.assertRaisesRegex(RuntimeError, 'stop'):
            rebuild_all.rebuild_dataset(
                self.dataset,
                'sam',
                atomic=True,
                runner=create_then_fail,
            )

        self.assertFalse(self.palace.exists())
        self.assertFalse(self.wiki.exists())
        self.assertFalse(self.dataset.joinpath('participants.json').exists())
        self.assertEqual(self.dataset.joinpath('dataset.json').read_text(), 'old-dataset')

    def test_non_atomic_failure_keeps_partial_changes(self):
        with self.assertRaisesRegex(RuntimeError, 'knowledge-graph failed'):
            rebuild_all.rebuild_dataset(
                self.dataset,
                'sam',
                atomic=False,
                runner=self._mutating_runner(fail_on='knowledge-graph'),
            )

        self.assertEqual(self.palace.joinpath('chroma.sqlite3').read_bytes(), b'new-vectors')
        self.assertEqual(self.dataset.joinpath('dataset.json').read_text(), 'new-dataset')
        self.assertFalse(self.dataset.joinpath('.rebuild.lock').exists())

    def test_existing_lock_blocks_second_rebuild(self):
        lock = self.dataset / '.rebuild.lock'
        lock.write_text('busy')

        with self.assertRaisesRegex(RuntimeError, 'Rebuild already in progress'):
            rebuild_all.rebuild_dataset(
                self.dataset,
                'sam',
                atomic=True,
                runner=lambda *_args: None,
            )

        self.assertTrue(lock.exists())


if __name__ == '__main__':
    unittest.main()
