from __future__ import annotations

import unittest
from unittest import mock

from scripts import pasi_multi_ai_planner as planner

class MultiAIPlannerTests(unittest.TestCase):
    def test_next_prompt_respects_dependencies(self) -> None:
        tasks = [
            {'id': 'a', 'title': 'A', 'objective': 'A', 'depends_on': [], 'acceptance_criteria': ['A'], 'verification': ['test']},
            {'id': 'b', 'title': 'B', 'objective': 'B', 'depends_on': ['a'], 'acceptance_criteria': ['B'], 'verification': ['test']},
        ]
        result = planner.next_prompt(tasks)
        self.assertEqual(result['task_id'], 'a')
        self.assertIn('PASI TASK a', result['prompt'])

    def test_preferred_order_wins_after_dependency_eligibility(self) -> None:
        tasks = [
            {'id': 'a', 'title': 'A', 'objective': 'A', 'depends_on': [], 'priority': 0, 'acceptance_criteria': ['A'], 'verification': ['test']},
            {'id': 'b', 'title': 'B', 'objective': 'B', 'depends_on': [], 'priority': 100, 'acceptance_criteria': ['B'], 'verification': ['test']},
        ]
        result = planner.next_prompt(list(reversed(tasks)))
        self.assertEqual(result['task_id'], 'b')
        self.assertEqual(result['mode'], 'preferred_order')

    def test_architect_cannot_invent_task_ids(self) -> None:
        deterministic = {'tasks': [{'id': 'a', 'title': 'A'}]}
        with mock.patch.object(planner, 'call_groq', return_value='{"tasks":[{"id":"b"}]}'):
            with self.assertRaisesRegex(planner.MultiAIError, 'identity set'):
                planner.architect_enrich('raw', deterministic)


    def test_cloud_chain_preserves_ids_and_uses_strategist_order(self) -> None:
        deterministic_tasks = [
            {
                'id': 'a',
                'title': 'A',
                'objective': 'A',
                'depends_on': [],
                'acceptance_criteria': ['A'],
                'verification': ['test'],
            },
            {
                'id': 'b',
                'title': 'B',
                'objective': 'B',
                'depends_on': [],
                'acceptance_criteria': ['B'],
                'verification': ['test'],
            },
        ]
        deterministic = {'schema_version': 1, 'tasks': deterministic_tasks, 'dissection': {'passes': []}}
        with mock.patch.object(planner, 'dissect', return_value=deterministic),              mock.patch.object(planner, 'call_groq', return_value='{"tasks":' + __import__('json').dumps(deterministic_tasks) + '}'),              mock.patch.object(planner, 'call_gemini', return_value='{"ranked_ids":["b","a"]}'):
            result = planner.plan('raw roadmap', use_cloud=True)
        self.assertEqual([item['id'] for item in result['tasks']], ['b', 'a'])
        self.assertTrue(result['planning']['architect'])
        self.assertTrue(result['planning']['strategist'])

    def test_planning_falls_back_without_cloud_credentials(self) -> None:
        result = planner.plan('- First task', use_cloud=False)
        self.assertEqual(result['planning']['fallback'], True)

if __name__ == '__main__':
    unittest.main()