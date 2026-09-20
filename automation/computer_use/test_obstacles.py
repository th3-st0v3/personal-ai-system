from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from automation.computer_use.obstacles import ObstacleLedger


class ObstacleLedgerTests(unittest.TestCase):
    def test_records_obstacle_and_writes_non_blocking_action_list(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = ObstacleLedger(root, root / "operator-state")
            first = ledger.record(
                "preapproval_required",
                "Need download from example.test",
                "Add a narrowly scoped preapproval if intended.",
                task_id="task-1",
                status="needs_preapproval",
            )
            self.assertTrue(first.obstacle_id.startswith("obs-"))
            self.assertIn(first.obstacle_id, (root / "operator-state" / "automation" / "action-list.md").read_text(encoding="utf-8"))
            values = (root / ".runtime" / "automation" / "obstacles.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(values), 1)
            payload = json.loads(values[0])
            self.assertEqual(payload["status"], "needs_preapproval")

    def test_deduplicates_pending_obstacles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger = ObstacleLedger(Path(directory), Path(directory) / "operator-state")
            first = ledger.record("missing_resource", "Need tool", "Install after approval", task_id="task-1")
            second = ledger.record("missing_resource", "Need tool", "Install after approval", task_id="task-1")
            self.assertEqual(first.obstacle_id, second.obstacle_id)
            self.assertEqual(len(ledger.pending()), 1)

    def test_state_is_outside_worktree_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_root = root / "operator-state"
            ledger = ObstacleLedger(root, state_root)
            ledger.record("test", "summary", "next")
            self.assertTrue((state_root / "automation" / "obstacles.jsonl").exists())
            self.assertFalse((root / ".runtime" / "automation" / "obstacles.jsonl").exists())

    def test_redacts_credentials_from_persisted_details(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger = ObstacleLedger(Path(directory))
            ledger.record(
                "provider_error",
                "request failed",
                "retry later",
                details={"Authorization": "Bearer super-secret-token", "api_key": "secret-value"},
            )
            raw = (Path(directory) / "operator-state" / "automation" / "obstacles.jsonl").read_text(encoding="utf-8")
            self.assertNotIn("super-secret-token", raw)
            self.assertNotIn("secret-value", raw)
            self.assertIn("[redacted]", raw)


if __name__ == "__main__":
    unittest.main()
