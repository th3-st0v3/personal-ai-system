from __future__ import annotations

import unittest

from scripts import pasi_dissection_adapter as adapter

class DissectionAdapterTests(unittest.TestCase):
    def test_three_pass_dissection_extracts_tasks_and_metadata(self) -> None:
        result = adapter.dissect('- Build bridge\n- Add telemetry after roadmap-001-build-bridge')
        self.assertEqual(len(result['tasks']), 2)
        self.assertEqual(result['dissection']['passes'][-1]['progress'], 100)

    def test_plain_text_paragraphs_are_supported(self) -> None:
        result = adapter.dissect('Build bridge\n\nAdd tests')
        self.assertEqual(len(result['tasks']), 2)

    def test_cycles_are_rejected(self) -> None:
        a = adapter.Candidate('a', 'a', 'a', 1, ('b',))
        b = adapter.Candidate('b', 'b', 'b', 2, ('a',))
        with self.assertRaisesRegex(adapter.DissectionError, 'cycle'):
            adapter.map_dependencies((a, b))

    def test_ai_enrichment_cannot_change_identity_set(self) -> None:
        def bad(_payload: str):
            return {'tasks': [{'id': 'invented'}]}
        with self.assertRaisesRegex(adapter.DissectionError, 'identity set'):
            adapter.dissect('- Task one', ai_json=bad)

if __name__ == '__main__':
    unittest.main()