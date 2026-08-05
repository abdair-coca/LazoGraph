#!/usr/bin/env python3
"""Regression tests for the MemPalace 3.x integration surface."""

import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import ingest
import init_knowledge
import query_kg


class FakeCollection:
    def __init__(self):
        self.upserts = []
        self.error = None

    def upsert(self, **kwargs):
        if self.error:
            raise self.error
        self.upserts.append(kwargs)


class FakeKnowledgeGraph:
    instances = []
    query_result = []
    stats_result = {'entities': 1, 'triples': 0}

    def __init__(self, db_path=None):
        self.db_path = db_path
        self.entities = []
        self.triples = []
        self.closed = False
        self.__class__.instances.append(self)

    def add_entity(self, name, entity_type='unknown', properties=None):
        self.entities.append((name, entity_type, properties))

    def add_triple(self, **kwargs):
        self.triples.append(kwargs)

    def query_entity(self, name, as_of=None, direction='outgoing'):
        return list(self.__class__.query_result)

    def stats(self):
        return dict(self.__class__.stats_result)

    def close(self):
        self.closed = True


class MemPalaceModules:
    def __init__(self):
        self.collection = FakeCollection()
        self.mempalace = types.ModuleType('mempalace')
        self.palace = types.ModuleType('mempalace.palace')
        self.knowledge_graph = types.ModuleType('mempalace.knowledge_graph')
        self.palace.get_collection = lambda *_args, **_kwargs: self.collection
        self.knowledge_graph.KnowledgeGraph = FakeKnowledgeGraph
        self.modules = {
            'mempalace': self.mempalace,
            'mempalace.palace': self.palace,
            'mempalace.knowledge_graph': self.knowledge_graph,
        }


class TestMemPalaceCompatibility(unittest.TestCase):
    def setUp(self):
        FakeKnowledgeGraph.instances.clear()
        FakeKnowledgeGraph.query_result = []
        self.fake = MemPalaceModules()
        self.tmp = tempfile.TemporaryDirectory()
        self.dataset = Path(self.tmp.name) / 'sam'
        self.dataset.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_vector_storage_uses_collection_upsert(self):
        messages = [{
            'role': 'assistant',
            'content': 'A durable memory.',
            'timestamp': '2026-08-05T12:00:00',
            'source_file': 'chat.txt',
            'source_type': 'whatsapp',
            'metadata': {},
        }]
        with patch.dict(sys.modules, self.fake.modules):
            stored = ingest._store_in_mempalace(self.dataset, 'sam', messages)

        self.assertEqual(stored, 1)
        upsert = self.fake.collection.upserts[0]
        self.assertEqual(upsert['documents'], ['A durable memory.'])
        self.assertEqual(upsert['metadatas'][0]['wing'], 'sam')
        self.assertEqual(upsert['metadatas'][0]['hall'], 'hall_voice')

    def test_kg_writer_uses_db_path_and_current_methods(self):
        relationships = [{
            'from': 'Alice',
            'to': 'sam',
            'type': 'friend_of',
            'timestamp': '2026-08-05T12:00:00',
            'source': 'chat.txt',
        }]
        with patch.dict(sys.modules, self.fake.modules):
            ingest._write_kg(
                self.dataset / '.mempalace' / 'palace',
                {'Alice'},
                relationships,
            )

        kg = FakeKnowledgeGraph.instances[0]
        self.assertTrue(kg.db_path.endswith('knowledge_graph.sqlite3'))
        self.assertEqual(kg.entities[0][:2], ('Alice', 'person'))
        self.assertEqual(kg.triples[0]['subject'], 'Alice')
        self.assertEqual(kg.triples[0]['predicate'], 'friend_of')
        self.assertTrue(kg.closed)

    def test_vector_failure_stops_before_dedup_backup(self):
        self.fake.collection.error = ValueError('embedding failed')
        messages = [{
            'role': 'assistant',
            'content': 'Do not mark this message as imported.',
            'timestamp': None,
            'source_file': 'chat.txt',
            'source_type': 'whatsapp',
            'metadata': {},
        }]
        with patch.dict(sys.modules, self.fake.modules):
            with self.assertRaisesRegex(RuntimeError, 'storage failed after 0/1'):
                ingest._store_in_mempalace(self.dataset, 'sam', messages)

    def test_query_loader_maps_current_kg_result(self):
        FakeKnowledgeGraph.query_result = [{
            'direction': 'incoming',
            'subject': 'Alice',
            'predicate': 'friend_of',
            'object': 'sam',
            'valid_from': None,
            'valid_to': None,
            'confidence': 1.0,
            'source_closet': None,
            'current': True,
        }]
        with patch.dict(sys.modules, self.fake.modules):
            entities, relationships = query_kg._load_kg(self.dataset)

        self.assertEqual(entities, {'Alice', 'sam'})
        self.assertEqual(relationships[0]['from'], 'Alice')
        self.assertEqual(relationships[0]['to'], 'sam')
        self.assertEqual(relationships[0]['type'], 'friend_of')

    def test_initializer_uses_current_api(self):
        palace_dir = self.dataset / '.mempalace'
        with patch.dict(sys.modules, self.fake.modules):
            init_knowledge.init_mempalace(palace_dir, 'sam')

        kg = FakeKnowledgeGraph.instances[0]
        self.assertEqual(kg.entities[0], ('sam', 'persona', {'name': 'sam'}))
        self.assertTrue(kg.closed)


if __name__ == '__main__':
    unittest.main()
