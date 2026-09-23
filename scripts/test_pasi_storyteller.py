from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.pasi_storyteller import build_story

class StorytellerTests(unittest.TestCase):
    def test_story_prefers_durable_handoff_and_bounds_recent_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = Path(temp_dir)
            (runtime / 'state.json').write_text(json.dumps({'run_id': 'old', 'current_task': 'old'}), encoding='utf-8')
            (runtime / 'handoff.json').write_text(json.dumps({'run_id': 'new', 'phase': 'automation', 'recent_tasks': list(map(str, range(20))), 'completed_tasks': 4}), encoding='utf-8')
            (runtime / 'events.jsonl').write_text(json.dumps({'kind': 'retry_started', 'timestamp': 'now'}) + '\n', encoding='utf-8')
            story = build_story(runtime)
        self.assertEqual(story['run_id'], 'new')
        self.assertEqual(story['completed_tasks'], 4)
        self.assertEqual(len(story['recent_tasks']), 8)
        self.assertEqual(story['recovery_events'][0]['kind'], 'retry_started')

if __name__ == '__main__':
    unittest.main()
