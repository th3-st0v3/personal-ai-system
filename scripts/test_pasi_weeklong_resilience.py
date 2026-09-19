from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from scripts import pasi_overnight_engine as legacy
from scripts import pasi_weeklong_resilience as resilience


class WeeklongResilienceTests(unittest.TestCase):
    def test_repair_timeout_is_bounded_but_allows_longer_engineering_responses(self) -> None:
        self.assertEqual(resilience.REPAIR_TIMEOUT_SECONDS, 30 * 60)

    def _complete_prefix(self) -> str:
        return "\n".join(
            (
                "PASI_RESULT_STATUS: complete",
                "PASI_RESULT_SUMMARY: completed the task",
                "PASI_RESULT_NEXT_TASK: inspect the next verified gap",
                "PASI_RESULT_REQUIREMENTS: complete",
                "PASI_RESULT_LIMITATIONS: handled",
                "PASI_RESULT_RESEARCH: not_applicable",
                "PASI_RESULT_UX: not_applicable",
                "PASI_RESULT_BACKEND: verified",
                "PASI_RESULT_EVIDENCE: python -m unittest scripts.test_pasi_weeklong_resilience",
                "PASI_RESULT_REPOSITORY_PROGRESS: changed",
                "PASI_RESULT_ALLOW_DELETE: false",
            )
        )

    def test_repair_prompt_contains_anti_loop_continuation_rule(self) -> None:
        now = datetime.now(timezone.utc)
        state = SimpleNamespace(
            schema_version=2,
            run_id="repair-test",
            started_at=now.isoformat(),
            deadline_at=(now + timedelta(hours=8)).isoformat(),
            worktree=str(Path.cwd()),
            branch="test",
            phase="engineering_os",
            current_task="Improve task continuation",
            recent_tasks=["already completed task"],
        )
        prompt = resilience._repair_prompt("Improve task continuation", "", "", state)
        self.assertIn("IF the CURRENT TASK is already satisfied", prompt)
        self.assertIn("THEN do not re-implement it", prompt)
        self.assertIn("next incomplete roadmap item", prompt)
        self.assertIn("PASI_RESULT_REPOSITORY_PROGRESS: stopped", prompt)

    def test_recovers_markerless_diff_from_response(self) -> None:
        response = self._complete_prefix() + "\n\nHere is the requested change:\n" + "\n".join(
            (
                "diff --git a/example.txt b/example.txt",
                "--- a/example.txt",
                "+++ b/example.txt",
                "@@ -1 +1 @@",
                "-old",
                "+new",
            )
        )
        parsed = resilience._parsed_response(response, legacy.parse_response)
        self.assertEqual(parsed[0], "complete")
        self.assertIn("diff --git a/example.txt b/example.txt", parsed[3])
        self.assertTrue(resilience._contract_valid(parsed))

    def test_recovers_fenced_diff_from_response(self) -> None:
        response = self._complete_prefix() + "\n\n```diff\n" + "\n".join(
            (
                "diff --git a/example.txt b/example.txt",
                "--- a/example.txt",
                "+++ b/example.txt",
                "@@ -1 +1 @@",
                "-old",
                "+new",
            )
        ) + "\n```\n"
        parsed = resilience._parsed_response(response, legacy.parse_response)
        self.assertIn("diff --git a/example.txt b/example.txt", parsed[3])
        self.assertNotIn("```", parsed[3])
        self.assertTrue(resilience._contract_valid(parsed))

    def test_accepts_conditional_no_change_completion(self) -> None:
        response = self._complete_prefix().replace(
            "PASI_RESULT_REPOSITORY_PROGRESS: changed",
            "PASI_RESULT_REPOSITORY_PROGRESS: stopped",
        ) + "\nPASI_RESULT_PATCH_BEGIN\nPASI_RESULT_PATCH_END\n"
        parsed = resilience._parsed_response(response, legacy.parse_response)
        self.assertTrue(resilience._contract_valid(parsed))

    def test_rejects_no_change_completion_without_stop_marker(self) -> None:
        response = self._complete_prefix() + "\nPASI_RESULT_PATCH_BEGIN\nPASI_RESULT_PATCH_END\n"
        parsed = resilience._parsed_response(response, legacy.parse_response)
        self.assertFalse(resilience._contract_valid(parsed))

    def test_archives_response_without_failing_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            worktree = Path(directory)
            resilience._archive_response(worktree, 3, 2, "response", label="primary")
            target = worktree / ".runtime" / "overnight" / "responses" / "task-0003-attempt-02-primary.txt"
            self.assertEqual(target.read_text(encoding="utf-8").strip(), "response")

    def test_pre_state_failure_is_restartable(self) -> None:
        deadline = datetime.now(timezone.utc) + timedelta(hours=1)
        self.assertFalse(resilience._should_not_restart(1, None, deadline))

    def test_manual_stop_is_not_restartable(self) -> None:
        deadline = datetime.now(timezone.utc) + timedelta(hours=1)
        state = SimpleNamespace(stop_reason="stopped")
        self.assertTrue(resilience._should_not_restart(0, state, deadline))

    def test_restart_budget_is_consecutive_and_resets_after_stable_runtime(self) -> None:
        self.assertEqual(resilience.MAX_CONSECUTIVE_RUNNER_RESTARTS, 8)
        self.assertEqual(resilience.RUNNER_STABILITY_RESET_SECONDS, 10 * 60)
        self.assertNotIn("MAX_RUNNER_RESTARTS", resilience.__dict__)

    def test_active_failure_state_is_restartable(self) -> None:
        deadline = datetime.now(timezone.utc) + timedelta(hours=1)
        state = SimpleNamespace(stop_reason="unexpected exception")
        self.assertFalse(resilience._should_not_restart(1, state, deadline))


if __name__ == "__main__":
    unittest.main()
