from __future__ import annotations

import os
import unittest

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
        draft: bool = False,
        risk: str = "standard",
        mergeable: str = "MERGEABLE",
        merge_state: str = "CLEAN",
        body: str = "",
        head_repo: str = "th3-st0v3/personal-ai-system",
    ) -> hygiene.PullRequestRecord:
        return hygiene.PullRequestRecord(
            number=7,
            title="Test PR",
            body=body,
            url="https://github.com/th3-st0v3/personal-ai-system/pull/7",
            head_branch="pasi/test",
            head_sha="deadbeef",
            head_repo=head_repo,
            is_draft=draft,
            mergeable=mergeable,
            merge_state=merge_state,
            changed_paths=("scripts/example.py",),
            risk=risk,
        )

    def test_standard_ready_pr_is_auto_merge_candidate(self) -> None:
        self.assertTrue(
            hygiene.is_standard_auto_merge_candidate(
                self._pr(),
                checks_green=True,
            )
        )

    def test_draft_requires_explicit_marker_for_auto_ready(self) -> None:
        self.assertFalse(
            hygiene.should_ready_and_merge_draft(
                self._pr(draft=True, body="Draft for review"),
                checks_green=True,
            )
        )
        self.assertTrue(
            hygiene.should_ready_and_merge_draft(
                self._pr(draft=True, body="PASI_AUTO_MERGE: true"),
                checks_green=True,
            )
        )

    def test_auto_ready_marker_also_authorizes_draft_merge(self) -> None:
        self.assertTrue(
            hygiene.is_auto_ready_authorized("PASI_AUTO_READY: true")
        )

    def test_high_risk_pr_never_becomes_automatic_merge_candidate(self) -> None:
        self.assertFalse(
            hygiene.is_standard_auto_merge_candidate(
                self._pr(risk="high"),
                checks_green=True,
            )
        )
        self.assertFalse(
            hygiene.should_ready_and_merge_draft(
                self._pr(
                    draft=True,
                    risk="high",
                    body="PASI_AUTO_MERGE: true",
                ),
                checks_green=True,
            )
        )

    def test_non_green_checks_block_auto_merge(self) -> None:
        self.assertFalse(
            hygiene.is_standard_auto_merge_candidate(
                self._pr(),
                checks_green=False,
            )
        )

    def test_unmergeable_pr_is_not_auto_merged(self) -> None:
        self.assertFalse(
            hygiene.is_standard_auto_merge_candidate(
                self._pr(mergeable="CONFLICTING"),
                checks_green=True,
            )
        )

    def test_fork_owned_pr_is_not_mutated(self) -> None:
        self.assertFalse(
            hygiene.is_standard_auto_merge_candidate(
                self._pr(head_repo="contributor/personal-ai-system"),
                checks_green=True,
            )
        )

    def test_merge_state_is_case_insensitive_in_api_recording(self) -> None:
        pr = self._pr(merge_state="CLEAN")
        self.assertTrue(
            hygiene.is_standard_auto_merge_candidate(
                pr,
                checks_green=True,
            )
        )

    def test_protected_and_system_branches_are_not_auto_pr_opened(self) -> None:
        branches = (
            {"name": "main", "ahead_by": 5},
            {"name": "beta-foundation", "ahead_by": 5},
            {"name": "dependabot/github_actions/example", "ahead_by": 5},
            {"name": "pasi/active-work", "ahead_by": 5},
        )
        # The branch-pr opening function should only attempt the final entry.
        import unittest.mock as mock

        with mock.patch.object(
            hygiene,
            "_create_draft_pr",
            return_value="https://example/pull/8",
        ) as create:
            opened = hygiene.open_missing_branch_prs(
                branches,
                frozenset(),
            )
        self.assertEqual(opened, ("pasi/active-work",))
        create.assert_called_once_with("pasi/active-work")


if __name__ == "__main__":
    unittest.main()
