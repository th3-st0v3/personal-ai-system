from __future__ import annotations

import unittest
from unittest.mock import patch

import scripts.pasi_promote as promote


class TestPasiPromote(unittest.TestCase):
    def test_high_risk_paths_are_review_gated(self) -> None:
        self.assertEqual(promote.classify_risk(["automation/chromium/pasi-chatgpt/recovery.js"]), "high")
        self.assertEqual(promote.classify_risk(["scripts/pasi_provider_router.py"]), "high")
        self.assertEqual(promote.classify_risk(["scripts/pasi_promote.py"]), "high")
        self.assertEqual(promote.classify_risk(["automation/orchestrator/bridge.py"]), "high")
        self.assertEqual(promote.classify_risk([".github/workflows/test.yml"]), "high")
        self.assertEqual(promote.classify_risk(["scripts/start_pasi_168h.sh"]), "high")
        self.assertEqual(promote.classify_risk(["docs/operations/pr-scope-policy.md"]), "high")
        self.assertEqual(promote.classify_risk(["SECURITY.md"]), "high")
        self.assertEqual(promote.classify_risk(["scripts/check_all.sh"]), "high")
        self.assertEqual(promote.classify_risk(["scripts/pasi_extended_runtime_entrypoint.py"]), "high")
        self.assertEqual(promote.classify_risk(["scripts/pasi_setup.py"]), "high")
        self.assertEqual(promote.classify_risk(["scripts/pasi_log_router.py"]), "high")

    def test_standard_changes_are_auto_merge_eligible(self) -> None:
        self.assertEqual(promote.classify_risk(["docs/readme.md", "scripts/test_example.py"]), "standard")

    def test_large_change_set_is_review_gated(self) -> None:
        paths = [f"docs/file-{index}.md" for index in range(promote.MAX_AUTOMERGE_FILES + 1)]
        self.assertEqual(promote.classify_risk(paths), "high")

    def test_broad_cross_subsystem_change_is_review_gated(self) -> None:
        paths = ("docs/readme.md", "scripts/example.py", "web/example.js")
        self.assertEqual(promote.classify_risk(paths), "high")

    def test_missing_gh_is_non_blocking(self) -> None:
        with patch.object(promote, "gh_available", return_value=False):
            result = promote.promote("abc123", "pasi/test", "task")
        self.assertFalse(result.auto_merge_requested)
        self.assertEqual(result.risk, "unknown")
        self.assertIn("not installed", result.message)

    def test_missing_gh_auth_is_non_blocking(self) -> None:
        with patch.object(promote, "gh_available", return_value=True):
            with patch.object(promote, "gh_authenticated", return_value=False):
                result = promote.promote("abc123", "pasi/test", "task")
        self.assertFalse(result.auto_merge_requested)
        self.assertIn("not authenticated", result.message)

    def test_standard_auto_merge_is_requested_before_checks_finish(self) -> None:
        with patch.object(promote, "gh_available", return_value=True):
            with patch.object(promote, "gh_authenticated", return_value=True):
                with patch.object(promote, "changed_paths", return_value=("docs/readme.md",)):
                    with patch.object(promote, "_branch_pr", return_value=(41, "https://github.com/th3-st0v3/personal-ai-system/pull/41", "OPEN")):
                        with patch.object(promote, "_enable_auto_merge", return_value=(True, "auto")) as enable:
                            result = promote.promote("abc123", "pasi/test", "task")
        enable.assert_called_once_with(41)
        self.assertTrue(result.auto_merge_requested)
        self.assertIn("required checks", result.message)

    def test_standard_auto_merge_proceeds_for_existing_pr(self) -> None:
        with patch.object(promote, "gh_available", return_value=True):
            with patch.object(promote, "gh_authenticated", return_value=True):
                with patch.object(promote, "changed_paths", return_value=("docs/readme.md",)):
                    with patch.object(promote, "_branch_pr", return_value=(42, "https://github.com/th3-st0v3/personal-ai-system/pull/42", "OPEN")):
                        with patch.object(promote, "_enable_auto_merge", return_value=(True, "auto")) as enable:
                            result = promote.promote("abc123", "pasi/test", "task")
        enable.assert_called_once_with(42)
        self.assertTrue(result.auto_merge_requested)

    def test_standard_auto_merge_does_not_require_reported_checks(self) -> None:
        with patch.object(promote, "gh_available", return_value=True):
            with patch.object(promote, "gh_authenticated", return_value=True):
                with patch.object(promote, "changed_paths", return_value=("docs/readme.md",)):
                    with patch.object(promote, "_branch_pr", return_value=(43, "https://github.com/th3-st0v3/personal-ai-system/pull/43", "OPEN")):
                        with patch.object(promote, "_enable_auto_merge", return_value=(True, "auto")) as enable:
                            result = promote.promote("abc123", "pasi/test", "task")
        enable.assert_called_once_with(43)
        self.assertTrue(result.auto_merge_requested)

    def test_open_task_pr_is_fast_forwarded_and_reused(self) -> None:
        with patch.object(promote, "gh_available", return_value=True):
            with patch.object(promote, "gh_authenticated", return_value=True):
                with patch.object(promote, "changed_paths", return_value=("docs/readme.md",)):
                    with patch.object(promote, "_branch_pr", return_value=(None, "", "")):
                        with patch.object(
                            promote,
                            "_find_open_task_pr",
                            return_value=(45, "https://github.com/th3-st0v3/personal-ai-system/pull/45", "pasi/existing", "base123"),
                        ):
                            with patch.object(
                                promote,
                                "_fast_forward_pr_branch",
                                return_value=(True, "fast-forwarded"),
                            ) as fast_forward:
                                with patch.object(promote, "_create_pr") as create:
                                    with patch.object(promote, "_enable_auto_merge", return_value=(True, "auto")):
                                        result = promote.promote("abc123", "pasi/new-branch", "task")
        fast_forward.assert_called_once_with("pasi/existing", "abc123", "base123")
        create.assert_not_called()
        self.assertEqual(result.pr_number, 45)
        self.assertTrue(result.auto_merge_requested)

    def test_open_task_pr_on_unrelated_branch_does_not_create_duplicate(self) -> None:
        with patch.object(promote, "gh_available", return_value=True):
            with patch.object(promote, "gh_authenticated", return_value=True):
                with patch.object(promote, "changed_paths", return_value=("docs/readme.md",)):
                    with patch.object(promote, "_branch_pr", return_value=(None, "", "")):
                        with patch.object(
                            promote,
                            "_find_open_task_pr",
                            return_value=(46, "https://github.com/th3-st0v3/personal-ai-system/pull/46", "pasi/existing", "base123"),
                        ):
                            with patch.object(
                                promote,
                                "_fast_forward_pr_branch",
                                return_value=(False, "not a fast-forward"),
                            ):
                                with patch.object(promote, "_create_pr") as create:
                                    result = promote.promote("abc123", "pasi/new-branch", "task")
        create.assert_not_called()
        self.assertEqual(result.pr_number, 46)
        self.assertFalse(result.auto_merge_requested)
        self.assertIn("no duplicate PR was created", result.message)

    def test_existing_closed_pr_is_never_reopened_or_duplicated(self) -> None:
        with patch.object(promote, "gh_available", return_value=True):
            with patch.object(promote, "gh_authenticated", return_value=True):
                with patch.object(promote, "changed_paths", return_value=("docs/readme.md",)):
                    with patch.object(promote, "_branch_pr", return_value=(44, "https://github.com/th3-st0v3/personal-ai-system/pull/44", "CLOSED")):
                        with patch.object(promote, "_create_pr") as create:
                            result = promote.promote("abc123", "pasi/test", "task")
        create.assert_not_called()
        self.assertEqual(result.pr_number, 44)
        self.assertFalse(result.auto_merge_requested)
        self.assertIn("remains closed", result.message)

    def test_existing_pr_gets_auto_merge_for_standard_changes(self) -> None:
        with patch.object(promote, "gh_available", return_value=True):
            with patch.object(promote, "gh_authenticated", return_value=True):
                with patch.object(promote, "changed_paths", return_value=("docs/readme.md",)):
                    with patch.object(promote, "_branch_pr", return_value=(42, "https://github.com/th3-st0v3/personal-ai-system/pull/42", "OPEN")):
                            with patch.object(promote, "_enable_auto_merge", return_value=(True, "auto")):
                                result = promote.promote("abc123", "pasi/test", "task")
        self.assertEqual(result.pr_number, 42)
        self.assertTrue(result.auto_merge_requested)
        self.assertEqual(result.risk, "standard")

    def test_existing_pr_does_not_auto_merge_high_risk_changes(self) -> None:
        with patch.object(promote, "gh_available", return_value=True):
            with patch.object(promote, "gh_authenticated", return_value=True):
                with patch.object(promote, "changed_paths", return_value=("automation/legacy/tampermonkey/chatgpt-controller.user.js",)):
                    with patch.object(promote, "_branch_pr", return_value=(43, "https://github.com/th3-st0v3/personal-ai-system/pull/43", "OPEN")):
                        with patch.object(promote, "_enable_auto_merge") as enable:
                            result = promote.promote("abc123", "pasi/test", "task")
        enable.assert_not_called()
        self.assertEqual(result.pr_number, 43)
        self.assertFalse(result.auto_merge_requested)
        self.assertEqual(result.risk, "high")


if __name__ == "__main__":
    unittest.main()
