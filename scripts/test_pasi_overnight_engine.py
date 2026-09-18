from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.pasi_overnight_engine import (
    RunnerState,
    choose_next_task,
    completion_contract_is_satisfied,
    parse_response,
)
from scripts.pasi_overnight_hardening import validate_patch_paths


class TestPasiOvernightEngine(unittest.TestCase):
    def test_completion_requires_explicit_evidence_contract(self) -> None:
        values = {
            "requirements": "complete",
            "limitations": "handled",
            "research": "performed",
            "ux": "verified",
            "backend": "verified",
            "evidence": "pytest and browser smoke test passed",
        }
        self.assertTrue(completion_contract_is_satisfied("complete", values))
        self.assertFalse(completion_contract_is_satisfied("needs_revision", values))
        values["requirements"] = "partial"
        self.assertFalse(completion_contract_is_satisfied("complete", values))

    def test_parse_response_extracts_patch_and_next_task(self) -> None:
        response = """PASI_RESULT_STATUS: complete
PASI_RESULT_SUMMARY: fixed the issue
PASI_RESULT_NEXT_TASK: improve monitoring
PASI_RESULT_REQUIREMENTS: complete
PASI_RESULT_LIMITATIONS: handled
PASI_RESULT_RESEARCH: performed
PASI_RESULT_UX: not_applicable
PASI_RESULT_BACKEND: verified
PASI_RESULT_EVIDENCE: pytest passed
PASI_RESULT_ALLOW_DELETE: false
PASI_RESULT_PATCH_BEGIN
diff --git a/example.txt b/example.txt
--- a/example.txt
+++ b/example.txt
@@ -1 +1 @@
-old
+new
PASI_RESULT_PATCH_END
"""
        status, summary, next_task, patch, allow_delete, values = parse_response(response)
        self.assertEqual(status, "complete")
        self.assertEqual(summary, "fixed the issue")
        self.assertEqual(next_task, "improve monitoring")
        self.assertIn("diff --git a/example.txt b/example.txt", patch)
        self.assertFalse(allow_delete)
        self.assertEqual(values["backend"], "verified")

    def test_parse_response_normalizes_markdown_wrapped_patch(self) -> None:
        response = """PASI_RESULT_STATUS: complete
PASI_RESULT_SUMMARY: fixed the issue
PASI_RESULT_NEXT_TASK: improve monitoring
PASI_RESULT_REQUIREMENTS: complete
PASI_RESULT_LIMITATIONS: handled
PASI_RESULT_RESEARCH: performed
PASI_RESULT_UX: not_applicable
PASI_RESULT_BACKEND: verified
PASI_RESULT_EVIDENCE: pytest passed
PASI_RESULT_ALLOW_DELETE: false
PASI_RESULT_PATCH_BEGIN
```diff
diff --git a/example.txt b/example.txt
--- a/example.txt
+++ b/example.txt
@@ -1 +1 @@
-old
+new
```
PASI_RESULT_PATCH_END
"""
        _, _, _, patch, _, _ = parse_response(response)
        self.assertEqual(patch, "diff --git a/example.txt b/example.txt\n--- a/example.txt\n+++ b/example.txt\n@@ -1 +1 @@\n-old\n+new\n")

    def test_parse_response_discards_prose_before_diff(self) -> None:
        response = """PASI_RESULT_STATUS: complete
PASI_RESULT_SUMMARY: fixed the issue
PASI_RESULT_NEXT_TASK: improve monitoring
PASI_RESULT_REQUIREMENTS: complete
PASI_RESULT_LIMITATIONS: handled
PASI_RESULT_RESEARCH: performed
PASI_RESULT_UX: not_applicable
PASI_RESULT_BACKEND: verified
PASI_RESULT_EVIDENCE: pytest passed
PASI_RESULT_ALLOW_DELETE: false
PASI_RESULT_PATCH_BEGIN
Here is the requested patch:
```diff
diff --git a/example.txt b/example.txt
--- a/example.txt
+++ b/example.txt
@@ -1 +1 @@
-old
+new
```
PASI_RESULT_PATCH_END
"""
        _, _, _, patch, _, _ = parse_response(response)
        self.assertIn("diff --git a/example.txt b/example.txt", patch)
        self.assertNotIn("Here is the requested patch:", patch)
        self.assertNotIn("```", patch)

    def test_new_file_patch_is_allowed_but_delete_requires_explicit_marker(self) -> None:
        new_file = """diff --git a/new.txt b/new.txt
new file mode 100644
--- /dev/null
+++ b/new.txt
@@ -0,0 +1 @@
+hello
"""
        validate_patch_paths(new_file, False)
        deletion = """diff --git a/old.txt b/old.txt
deleted file mode 100644
--- a/old.txt
+++ /dev/null
@@ -1 +0,0 @@
-old
"""
        with self.assertRaises(ValueError):
            validate_patch_paths(deletion, False)
        validate_patch_paths(deletion, True)

    def test_unattended_patch_rejects_symlink_and_secret_paths(self) -> None:
        symlink = """diff --git a/link b/link
new file mode 120000
--- /dev/null
+++ b/link
@@ -0,0 +1 @@
+/tmp/target
"""
        with self.assertRaises(ValueError):
            validate_patch_paths(symlink, False)

        secret = """diff --git a/.env b/.env
--- a/.env
+++ b/.env
@@ -1 +1 @@
-A=1
+A=2
"""
        with self.assertRaises(ValueError):
            validate_patch_paths(secret, False)

    def test_build_prompt_contains_anti_loop_continuation_rule(self) -> None:
        state = RunnerState(
            run_id="prompt-test",
            started_at="2026-01-01T00:00:00+00:00",
            deadline_at="2026-01-01T10:00:00+00:00",
            worktree=str(Path.cwd()),
            branch="test",
            current_task="Improve task continuation",
            recent_tasks=["already completed task"],
        )
        prompt = build_prompt(state.current_task, state, "")
        self.assertIn("IF the CURRENT TASK is already satisfied", prompt)
        self.assertIn("THEN do not re-implement it", prompt)
        self.assertIn("next incomplete roadmap item", prompt)
        self.assertIn("RECENT TASKS:", prompt)

    def test_choose_next_task_avoids_recent_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = RunnerState(
                run_id="test",
                started_at="2026-01-01T00:00:00+00:00",
                deadline_at="2026-01-01T10:00:00+00:00",
                worktree=str(Path(directory)),
                branch="test",
                current_task="first",
                recent_tasks=["candidate"],
            )
            self.assertNotEqual(choose_next_task(state, "candidate"), "candidate")


if __name__ == "__main__":
    unittest.main()
