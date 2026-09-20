from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from automation.computer_use.state_paths import resolve_state_root, resolve_state_path


class StatePathTests(unittest.TestCase):
    def test_default_state_root_is_external_to_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            worktree = Path(directory) / "worktree"
            state = Path(directory) / "state"
            worktree.mkdir()
            self.assertEqual(resolve_state_root(worktree, state), state.resolve())
            self.assertNotEqual(worktree, state)

    def test_state_root_inside_worktree_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            worktree = Path(directory) / "worktree"
            worktree.mkdir()
            with self.assertRaises(ValueError):
                resolve_state_root(worktree, worktree / ".runtime")

    def test_relative_state_path_is_resolved_from_external_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            worktree = Path(directory) / "worktree"
            state = Path(directory) / "state"
            worktree.mkdir()
            state.mkdir()
            resolved = resolve_state_path(
                Path("policy/preapprovals.json"),
                state_root=state,
                repo_root=worktree,
            )
            self.assertEqual(resolved, (state / "policy/preapprovals.json").resolve())

    def test_state_path_inside_worktree_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            worktree = Path(directory) / "worktree"
            state = Path(directory) / "state"
            worktree.mkdir()
            state.mkdir()
            with self.assertRaises(ValueError):
                resolve_state_path(
                    worktree / ".runtime" / "policy.json",
                    state_root=state,
                    repo_root=worktree,
                )


if __name__ == "__main__":
    unittest.main()
