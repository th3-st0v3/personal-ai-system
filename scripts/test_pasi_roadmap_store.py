from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.pasi_roadmap_store import RoadmapError, RoadmapStore

class RoadmapStoreTests(unittest.TestCase):
    def test_multiple_roadmaps_can_be_selected_and_archived(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = RoadmapStore(Path(directory) / 'catalog.json')
            first = store.create('Core', tasks=[{'id': 'a'}])
            second = store.create('UI', tasks=[{'id': 'b'}])
            self.assertEqual(store.list()['active_roadmap_id'], second['id'])
            store.select(first['id'])
            self.assertEqual(store.active()['id'], first['id'])
            store.archive(first['id'])
            self.assertIsNone(store.active())

    def test_archived_roadmap_cannot_be_mutated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = RoadmapStore(Path(directory) / 'catalog.json')
            item = store.create('Core')
            store.archive(item['id'])
            with self.assertRaisesRegex(RoadmapError, 'missing or archived'):
                store.replace_tasks(item['id'], [{'id': 'x'}])

    def test_combine_remaps_colliding_task_ids_and_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = RoadmapStore(Path(directory) / 'catalog.json')
            first = store.create('A', tasks=[{'id': 'task-1'}, {'id': 'task-2', 'depends_on': ['task-1']}])
            second = store.create('B', tasks=[{'id': 'task-1'}, {'id': 'task-3', 'depends_on': ['task-1']}])
            combined = store.combine([first['id'], second['id']], 'Combined')
            ids = [task['id'] for task in combined['tasks']]
            self.assertEqual(len(ids), len(set(ids)))
            self.assertEqual(combined['source_ids'], [first['id'], second['id']])
            dep_task = next(task for task in combined['tasks'] if task['id'].endswith('task-3'))
            self.assertTrue(dep_task['depends_on'][0].startswith(second['id'][:12] + '-'))

if __name__ == '__main__':
    unittest.main()