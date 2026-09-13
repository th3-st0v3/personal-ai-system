import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import openrouter_build_loop as loop


class TestOpenRouterBuildLoop(unittest.TestCase):
    def test_default_state_has_safe_approval_queue(self):
        state = loop.default_state()
        self.assertEqual(state["phase"], "beta")
        self.assertEqual(state["approval_queue"], [])
        self.assertLessEqual(loop.DEFAULT_MAX_DAILY_REQUESTS, 50)

    def test_state_checkpoint_is_atomic_and_round_trips(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            state = loop.default_state()
            loop.save_state(path, state)
            self.assertEqual(loop.load_state(path), state)
            self.assertFalse(path.with_suffix(".json.tmp").exists())

    def test_unsafe_paths_are_rejected(self):
        proposal = {
            "action_justification": "test",
            "file_path": "../outside.py",
            "code_to_execute": "pass",
            "new_state": {},
        }
        with self.assertRaises(ValueError):
            loop.validate_proposal(proposal)

    def test_absolute_paths_are_rejected(self):
        proposal = {
            "action_justification": "test",
            "file_path": "/tmp/outside.py",
            "code_to_execute": "pass",
            "new_state": {},
        }
        with self.assertRaises(ValueError):
            loop.validate_proposal(proposal)

    def test_proposal_is_queued_without_writing_target_file(self):
        state = loop.default_state()
        proposal = {
            "action_justification": "Add a harmless test",
            "file_path": "src/example.py",
            "code_to_execute": "pass\n",
            "new_state": {"backlog": ["next"], "completed_tasks": ["done"]},
        }
        loop.enqueue_proposal(state, proposal)
        item = state["approval_queue"][-1]
        self.assertEqual(item["status"], "pending_review")
        self.assertEqual(item["file_path"], "src/example.py")
        self.assertEqual(state["backlog"], ["next"])
        self.assertFalse(Path("src/example.py").exists())

    @patch("scripts.openrouter_build_loop.time.sleep")
    def test_budget_wait_uses_last_request_timestamp(self, sleep):
        state = loop.default_state()
        state["last_request_at"] = loop.utc_now()
        loop.sleep_for_budget(state, 30)
        sleep.assert_called_once()
        self.assertGreaterEqual(sleep.call_args.args[0], 0)

    def test_serialized_state_is_json(self):
        state = loop.default_state()
        self.assertIsInstance(json.dumps(state), str)


if __name__ == "__main__":
    unittest.main()
