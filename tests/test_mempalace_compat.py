#!/usr/bin/env python3
"""Regression tests for the MemPalace 3.x integration surface."""

import json
import sqlite3
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
        self.assertEqual(kg.triples[0]['valid_from'], '2026-08-05')
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
            entities, relationships, native_stats = query_kg._load_kg(self.dataset)

        self.assertEqual(entities, {'Alice', 'sam'})
        self.assertEqual(relationships[0]['from'], 'Alice')
        self.assertEqual(relationships[0]['to'], 'sam')
        self.assertEqual(relationships[0]['type'], 'friend_of')
        self.assertEqual(native_stats, {'entities': 1, 'triples': 0})

    def test_initializer_uses_current_api(self):
        palace_dir = self.dataset / '.mempalace'
        with patch.dict(sys.modules, self.fake.modules):
            init_knowledge.init_mempalace(palace_dir, 'sam')

        kg = FakeKnowledgeGraph.instances[0]
        self.assertEqual(kg.entities[0], ('sam', 'persona', {'name': 'sam'}))
        self.assertTrue(kg.closed)

    def test_spanish_relationships_and_chat_participants_are_extracted(self):
        messages = [
            {
                'role': 'assistant',
                'content': 'Mi amiga Carla vino. Después hablé con Diego.',
                'timestamp': '2026-08-05T12:00:00',
                'source_file': 'chat.txt',
                'source_type': 'whatsapp',
                'metadata': {'sender': 'Abdair'},
            },
            {
                'role': 'user',
                'content': 'Respuesta uno.',
                'timestamp': '2026-08-05T12:01:00',
                'source_file': 'chat.txt',
                'source_type': 'whatsapp',
                'metadata': {'sender': 'Alizon'},
            },
            {
                'role': 'user',
                'content': 'Respuesta dos.',
                'timestamp': '2026-08-05T12:02:00',
                'source_file': 'chat.txt',
                'source_type': 'whatsapp',
                'metadata': {'sender': 'Alizon'},
            },
        ]

        with patch.object(ingest, '_write_kg') as write_kg:
            stats = ingest._extract_kg_triples(self.dataset, messages)

        entities = write_kg.call_args.args[1]
        relationships = write_kg.call_args.args[2]
        relationship_keys = {
            (rel['from'], rel['to'], rel['type']) for rel in relationships
        }

        self.assertEqual(stats, {'entities': 4, 'relationships': 4})
        self.assertEqual(entities, {'Abdair', 'Alizon', 'Carla', 'Diego'})
        self.assertIn(('Abdair', 'sam', 'participant_in'), relationship_keys)
        self.assertIn(('Alizon', 'sam', 'participant_in'), relationship_keys)
        self.assertIn(('Abdair', 'Alizon', 'communicates_with'), relationship_keys)
        self.assertIn(('Carla', 'Abdair', 'friend_of'), relationship_keys)

        profiles = ingest._write_participant_profiles(self.dataset, messages)
        self.assertEqual(profiles[0]['name'], 'Abdair')
        self.assertEqual(profiles[0]['identity_type'], 'persona')
        self.assertEqual(profiles[0]['message_count'], 1)
        self.assertEqual(profiles[1]['name'], 'Alizon')
        self.assertEqual(profiles[1]['identity_type'], 'contact')
        self.assertEqual(profiles[1]['message_count'], 2)

    def test_rebuild_clear_preserves_unmanaged_relationships(self):
        db_path = self.dataset / '.mempalace' / 'palace' / 'knowledge_graph.sqlite3'
        db_path.parent.mkdir(parents=True)
        connection = sqlite3.connect(db_path)
        connection.execute(
            'CREATE TABLE triples (id INTEGER PRIMARY KEY, adapter_name TEXT)'
        )
        connection.executemany(
            'INSERT INTO triples (adapter_name) VALUES (?)',
            [('persona-knowledge',), ('manual',), (None,)],
        )
        connection.commit()
        connection.close()

        cleared = ingest._clear_managed_kg(self.dataset)

        connection = sqlite3.connect(db_path)
        remaining = connection.execute(
            'SELECT adapter_name FROM triples ORDER BY id'
        ).fetchall()
        connection.close()
        self.assertEqual(cleared, 1)
        self.assertEqual(remaining, [('manual',), (None,)])

    def test_query_loader_discovers_direct_participant_relationship(self):
        profiles = [
            {'name': 'Abdair', 'identity_type': 'persona'},
            {'name': 'Alizon', 'identity_type': 'contact'},
        ]
        FakeKnowledgeGraph.query_result = [{
            'subject': 'Abdair',
            'predicate': 'communicates_with',
            'object': 'Alizon',
            'valid_from': '2026-08-05',
            'confidence': 1.0,
            'source_closet': None,
        }]

        with patch.dict(sys.modules, self.fake.modules):
            entities, relationships, _ = query_kg._load_kg(
                self.dataset,
                profiles=profiles,
            )

        self.assertEqual(entities, {'sam', 'Abdair', 'Alizon'})
        self.assertEqual(len(relationships), 1)
        self.assertEqual(relationships[0]['from'], 'Abdair')
        self.assertEqual(relationships[0]['to'], 'Alizon')

    def test_fuzzy_match_prefers_person_name_over_dataset_slug(self):
        matched = query_kg._fuzzy_match(
            'Abdair',
            {'abdair-e2e', 'Abdair Coca', 'Alizon'},
        )

        self.assertEqual(matched, 'Abdair Coca')

    def test_stored_messages_are_loaded_uniquely_for_kg_rebuild(self):
        sources = self.dataset / 'sources'
        sources.mkdir()
        message = {
            'role': 'user',
            'content': 'Mensaje repetido.',
            'timestamp': None,
            'source_file': 'chat.txt',
            'source_type': 'whatsapp',
            'metadata': {'sender': 'Alizon'},
        }
        line = json.dumps(message, ensure_ascii=False) + '\n'
        (sources / 'one.jsonl').write_text(line, encoding='utf-8')
        (sources / 'two.jsonl').write_text(line, encoding='utf-8')

        messages = ingest._load_stored_messages(self.dataset)

        self.assertEqual(messages, [message])

    def test_rebuild_replaces_kg_stats_without_changing_message_counts(self):
        metadata = {
            'stats': {
                'sources': 1,
                'total_messages': 3627,
                'assistant_turns': 2113,
                'kg_entities': 0,
                'kg_relationships': 0,
            }
        }
        metadata_path = self.dataset / 'dataset.json'
        metadata_path.write_text(json.dumps(metadata), encoding='utf-8')

        ingest._set_kg_stats(
            self.dataset,
            {'entities': 3, 'relationships': 1},
        )

        updated = json.loads(metadata_path.read_text(encoding='utf-8'))['stats']
        self.assertEqual(updated['total_messages'], 3627)
        self.assertEqual(updated['assistant_turns'], 2113)
        self.assertEqual(updated['kg_entities'], 3)
        self.assertEqual(updated['kg_relationships'], 1)


if __name__ == '__main__':
    unittest.main()
