from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts import pasi_overnight_engine as legacy
from scripts import pasi_weeklong_resilience as resilience


class WeeklongResilienceTests(unittest.TestCase):
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
                "PASI_RESULT_ALLOW_DELETE: false",
            )
        )

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

    def test_rejects_completion_without_patch(self) -> None:
        response = self._complete_prefix() + "\nPASI_RESULT_PATCH_BEGIN\nPASI_RESULT_PATCH_END\n"
        parsed = resilience._parsed_response(response, legacy.parse_response)
        self.assertFalse(resilience._contract_valid(parsed))

    def test_archives_response_without_failing_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            worktree = Path(directory)
            resilience._archive_response(worktree, 3, 2, "response", label="primary")
            target = worktree / ".runtime" / "overnight" / "responses" / "task-0003-attempt-02-primary.txt"
            self.assertEqual(target.read_text(encoding="utf-8").strip(), "response")


if __name__ == "__main__":
    unittest.main()
