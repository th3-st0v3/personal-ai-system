from __future__ import annotations

import os
import unittest
from unittest import mock

from scripts import reconcile_branch_prs as hygiene


class TestBranchPrReconciliation(unittest.TestCase):
    def setUp(self) -> None:
        self._repository = os.environ.get("GITHUB_REPOSITORY")
        os.environ["GITHUB_REPOSITORY"] = "th3-st0v3/personal-ai-system"

    def tearDown(self) -> None:
        if self._repository is None:
            os.environ.pop("GITHUB_REPOSITORY", None)
        else:
            os.environ["GITHUB_REPOSITORY"] = self._repository

    def _pr(
        self,
        *,
        number: int = 7,
        branch: str = "pasi/test",
        draft: bool = False,
        merged_at: str | None = None,
        risk: str = "standard",
        mergeable: str = "MERGEABLE",
        merge_state: str = "CLEAN",
        body: str = "",
        head_repo: str = "th3-st0v3/personal-ai-system",
    ) -> hygiene.PullRequestRecord:
        return hygiene.PullRequestRecord(
            number=number,
            title="Test PR",
            body=body,
            url=f"https://github.com/th3-st0v3/personal-ai-system/pull/{number}",
            head_branch=branch,
            head_sha="deadbeef",
            head_repo=head_repo,
            is_draft=draft,
            merged_at=merged_at,
            mergeable=mergeable,
            merge_state=merge_state,
            changed_paths=("scripts/example.py",),
            risk=risk,
            updated_at="2026-09-22T20:00:00Z",
        )

    def test_ready_standard_pr_is_merge_candidate(self) -> None:
        self.assertTrue(hygiene.is_merge_candidate(self._pr(), checks_green=True))

    def test_failed_checks_never_make_pr_mergeable(self) -> None:
        self.assertFalse(hygiene.is_merge_candidate(self._pr(), checks_green=False))

    def test_hygiene_managed_draft_requires_marker(self) -> None:
        self.assertFalse(
            hygiene.is_hygiene_managed_draft_candidate(
                self._pr(draft=True, body="ordinary draft"),
                checks_green=True,
            )
        )
        self.assertTrue(
            hygiene.is_hygiene_managed_draft_candidate(
                self._pr(draft=True, body="PASI_AUTO_READY: true"),
                checks_green=True,
            )
        )

    def test_high_risk_pr_is_not_automatic_merge_candidate(self) -> None:
        self.assertFalse(
            hygiene.is_merge_candidate(self._pr(risk="high"), checks_green=True)
        )

    def test_fork_owned_pr_is_not_mutated(self) -> None:
        self.assertFalse(
            hygiene.is_merge_candidate(
                self._pr(head_repo="contributor/personal-ai-system"),
                checks_green=True,
            )
        )

    def test_protected_and_system_branches_are_skipped(self) -> None:
        branches = (
            {"name": "main"},
            {"name": "beta-foundation"},
            {"name": "dependabot/example"},
            {"name": "renovate/example"},
            {"name": "pasi/active"},
        )
        with mock.patch.object(hygiene, "_branch_ahead", side_effect=lambda name: 3):
            with mock.patch.object(
                hygiene, "_create_draft_pr", return_value="https://example/pull/8"
            ) as create:
                result = hygiene.reconcile_branches(branches, (), ())
        self.assertEqual(result.opened_prs, ("pasi/active",))
        create.assert_called_once_with("pasi/active")

    def test_unnecessary_branch_is_deleted(self) -> None:
        branches = ({"name": "feat/finished"},)
        with mock.patch.object(hygiene, "_branch_ahead", return_value=0):
            with mock.patch.object(hygiene, "_delete_branch", return_value=True) as delete:
                result = hygiene.reconcile_branches(branches, (), ())
        self.assertEqual(result.deleted_branches, ("feat/finished",))
        delete.assert_called_once_with("feat/finished")

    def test_closed_unmerged_pr_with_unique_work_is_reopened(self) -> None:
        closed = self._pr(number=19, branch="fix/unfinished")
        branches = ({"name": "fix/unfinished"},)
        with mock.patch.object(hygiene, "_branch_ahead", return_value=4):
            with mock.patch.object(hygiene, "_reopen_pr", return_value=True) as reopen:
                result = hygiene.reconcile_branches(branches, (), (closed,))
        self.assertEqual(result.reopened_prs, (19,))
        reopen.assert_called_once_with(19)

    def test_closed_merged_pr_with_new_work_gets_new_draft(self) -> None:
        closed = self._pr(number=20, branch="feat/after-merge", merged_at="2026-09-21T00:00:00Z")
        branches = ({"name": "feat/after-merge"},)
        with mock.patch.object(hygiene, "_branch_ahead", return_value=2):
            with mock.patch.object(hygiene, "_create_draft_pr", return_value="draft") as create:
                result = hygiene.reconcile_branches(branches, (), (closed,))
        self.assertEqual(result.opened_prs, ("feat/after-merge",))
        create.assert_called_once_with("feat/after-merge")

    def test_existing_open_branch_is_not_reconciled_twice(self) -> None:
        pr = self._pr(branch="feat/open")
        branches = ({"name": "feat/open"},)
        with mock.patch.object(hygiene, "_branch_ahead", return_value=4) as ahead:
            result = hygiene.reconcile_branches(branches, (pr,), ())
        self.assertEqual(result, hygiene.ReconciliationResult())
        ahead.assert_not_called()

    def test_merge_state_and_mergeable_must_be_current(self) -> None:
        self.assertFalse(
            hygiene.is_merge_candidate(
                self._pr(merge_state="DIRTY"),
                checks_green=True,
            )
        )
        self.assertFalse(
            hygiene.is_merge_candidate(
                self._pr(mergeable="CONFLICTING"),
                checks_green=True,
            )
        )


if __name__ == "__main__":
    unittest.main()
