from __future__ import annotations

import unittest
from unittest.mock import patch

import scripts.pasi_promote as promote


class TestPasiPromote(unittest.TestCase):
    def test_high_risk_paths_are_review_gated(self) -> None:
        self.assertEqual(promote.classify_risk(["automation/chromium/pasi-chatgpt/recovery.js"]), "high")
        self.assertEqual(promote.classify_risk(["scripts/pasi_provider_router.py"]), "high")
        self.assertEqual(promote.classify_risk([".github/workflows/test.yml"]), "high")

    def test_standard_changes_are_auto_merge_eligible(self) -> None:
        self.assertEqual(promote.classify_risk(["docs/readme.md", "scripts/test_example.py"]), "standard")

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

    def test_existing_closed_pr_is_reopened_instead_of_creating_duplicate(self) -> None:
        with patch.object(promote, "gh_available", return_value=True):
            with patch.object(promote, "gh_authenticated", return_value=True):
                with patch.object(promote, "changed_paths", return_value=("docs/readme.md",)):
                    with patch.object(promote, "_branch_pr", return_value=(44, "https://github.com/th3-st0v3/personal-ai-system/pull/44", "CLOSED")):
                        with patch.object(promote, "_reopen_pr", return_value=(True, "reopened")) as reopen:
                            with patch.object(promote, "_create_pr") as create:
                                with patch.object(promote, "_enable_auto_merge", return_value=(True, "auto")):
                                    result = promote.promote("abc123", "pasi/test", "task")
        reopen.assert_called_once_with(44)
        create.assert_not_called()
        self.assertEqual(result.pr_number, 44)
        self.assertTrue(result.auto_merge_requested)

    def test_existing_pr_gets_auto_merge_for_standard_changes(self) -> None:
        with patch.object(promote, "gh_available", return_value=True):
            with patch.object(promote, "gh_authenticated", return_value=True):
                with patch.object(promote, "changed_paths", return_value=("docs/readme.md",)):
                    with patch.object(promote, "_existing_pr", return_value=(42, "https://github.com/th3-st0v3/personal-ai-system/pull/42")):
                        with patch.object(promote, "_enable_auto_merge", return_value=(True, "auto")):
                            result = promote.promote("abc123", "pasi/test", "task")
        self.assertEqual(result.pr_number, 42)
        self.assertTrue(result.auto_merge_requested)
        self.assertEqual(result.risk, "standard")

    def test_existing_pr_does_not_auto_merge_high_risk_changes(self) -> None:
        with patch.object(promote, "gh_available", return_value=True):
            with patch.object(promote, "gh_authenticated", return_value=True):
                with patch.object(promote, "changed_paths", return_value=("automation/tampermonkey/chatgpt-controller.user.js",)):
                    with patch.object(promote, "_existing_pr", return_value=(43, "https://github.com/th3-st0v3/personal-ai-system/pull/43")):
                        with patch.object(promote, "_enable_auto_merge") as enable:
                            result = promote.promote("abc123", "pasi/test", "task")
        enable.assert_not_called()
        self.assertEqual(result.pr_number, 43)
        self.assertFalse(result.auto_merge_requested)
        self.assertEqual(result.risk, "high")


if __name__ == "__main__":
    unittest.main()
