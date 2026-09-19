from __future__ import annotations

import unittest
import unittest.mock

from scripts.cleanup_duplicate_branches import (
    BranchRef,
    build_cleanup_plan,
    can_delete_merged_branch,
    is_disposable_name,
    list_superseded_snapshot_branches,
    _list_merged_pr_head_shas_for_branches,)


class TestCleanupDuplicateBranches(unittest.TestCase):
    def test_disposable_suffixes_are_classified(self) -> None:
        for branch in (
            "pasi/example-pr",
            "pasi/example-pr2",
            "pasi/example-final",
            "pasi/example-final3",
            "pasi/example-v2",
            "pasi/example-head",
            "pasi/example-verified",
            "pasi/example-check2",
            "pasi/example-current",
            "pasi/example-submit",
            "pasi/example-merge",
        ):
            self.assertTrue(is_disposable_name(branch))

    def test_canonical_non_snapshot_branch_wins(self) -> None:
        branches = (
            BranchRef("pasi/feature", "abc"),
            BranchRef("pasi/feature-final", "abc"),
            BranchRef("pasi/feature-pr", "abc"),
        )
        plan = build_cleanup_plan(
            branches,
            open_pr_heads=frozenset(),
            merged_pr_heads={},
        )
        self.assertEqual([item.name for item in plan.keepers], ["pasi/feature"])
        self.assertEqual(
            {item.name for item in plan.deletions},
            {"pasi/feature-final", "pasi/feature-pr"},
        )

    def test_merged_pr_lookup_by_branch_handles_squash_merge(self) -> None:
        branch = BranchRef(
            "codex/easy-local-validation",
            "d9f6a1ed3966a53b701b289b018813bdff36d6ea",
        )

        with unittest.mock.patch.dict(
            "os.environ",
            {"GITHUB_REPOSITORY": "th3-st0v3/personal-ai-system"},
            clear=False,
        ), unittest.mock.patch(
            "scripts.cleanup_duplicate_branches._request_json",
            return_value=[
                {
                    "merged_at": "2026-09-16T23:25:57Z",
                    "head": {
                        "ref": "codex/easy-local-validation",
                        "sha": "d9f6a1ed3966a53b701b289b018813bdff36d6ea",
                        "repo": {"full_name": "th3-st0v3/personal-ai-system"},
                    },
                }
            ],
        ) as request:
            merged = _list_merged_pr_head_shas_for_branches(
                (branch,),
                token="test-token",
            )

        request.assert_called_once_with(
            "commits/d9f6a1ed3966a53b701b289b018813bdff36d6ea/pulls?per_page=100",
            token="test-token",
        )
        self.assertEqual(
            merged,
            {
                "codex/easy-local-validation": frozenset(
                    {"d9f6a1ed3966a53b701b289b018813bdff36d6ea"}
                )
            },
        )

    def test_merged_duplicate_branch_is_not_the_keeper(self) -> None:
        branches = (
            BranchRef("feature/local-byte-storage", "abc"),
            BranchRef("feature/local-byte-storage-final", "abc"),
        )
        plan = build_cleanup_plan(
            branches,
            open_pr_heads=frozenset(),
            merged_pr_heads={"feature/local-byte-storage": frozenset({"abc"})},
        )
        self.assertEqual([item.name for item in plan.keepers], ["feature/local-byte-storage"])

    def test_unique_merged_pr_head_is_safe_to_delete(self) -> None:
        branches = (BranchRef("feature/merged", "abc"),)
        plan = build_cleanup_plan(
            branches,
            open_pr_heads=frozenset(),
            merged_pr_heads={"feature/merged": frozenset({"abc"})},
        )
        self.assertEqual([item.name for item in plan.deletions], ["feature/merged"])

    def test_advanced_merged_pr_head_is_preserved(self) -> None:
        branches = (BranchRef("feature/merged", "newsha"),)
        plan = build_cleanup_plan(
            branches,
            open_pr_heads=frozenset(),
            merged_pr_heads={"feature/merged": frozenset({"oldsha"})},
        )
        self.assertEqual(plan.deletions, ())

    def test_closed_unmerged_pr_branch_is_safe_only_when_fully_merged(self) -> None:
        branches = (BranchRef("feature/closed-unmerged", "main-tip"),)
        plan = build_cleanup_plan(
            branches,
            open_pr_heads=frozenset(),
            merged_pr_heads={},
            fully_merged_branches=frozenset({"feature/closed-unmerged"}),
        )
        self.assertEqual(
            [item.name for item in plan.deletions],
            ["feature/closed-unmerged"],
        )

    def test_closed_unmerged_pr_branch_is_preserved_when_not_fully_merged(self) -> None:
        branches = (BranchRef("feature/closed-unmerged", "feature-tip"),)
        plan = build_cleanup_plan(
            branches,
            open_pr_heads=frozenset(),
            merged_pr_heads={},
            fully_merged_branches=frozenset(),
        )
        self.assertEqual(plan.deletions, ())

    def test_fully_merged_branch_is_safe_to_delete(self) -> None:
        branches = (BranchRef("feature/merged", "main-tip"),)
        plan = build_cleanup_plan(
            branches,
            open_pr_heads=frozenset(),
            merged_pr_heads={},
            fully_merged_branches=frozenset({"feature/merged"}),
        )
        self.assertEqual([item.name for item in plan.deletions], ["feature/merged"])

    def test_fully_merged_open_pr_head_is_preserved(self) -> None:
        branches = (BranchRef("feature/open", "main-tip"),)
        plan = build_cleanup_plan(
            branches,
            open_pr_heads=frozenset({"feature/open"}),
            merged_pr_heads={},
            fully_merged_branches=frozenset({"feature/open"}),
        )
        self.assertEqual(plan.deletions, ())

    def test_open_pr_head_is_never_deleted(self) -> None:
        branches = (
            BranchRef("pasi/feature", "abc"),
            BranchRef("pasi/feature-pr", "abc"),
        )
        plan = build_cleanup_plan(
            branches,
            open_pr_heads=frozenset({"pasi/feature-pr"}),
            merged_pr_heads={},
        )
        self.assertEqual([item.name for item in plan.deletions], ["pasi/feature"])

    def test_main_is_never_deleted(self) -> None:
        branches = (
            BranchRef("main", "abc"),
            BranchRef("pasi/snapshot", "abc"),
        )
        plan = build_cleanup_plan(
            branches,
            open_pr_heads=frozenset(),
            merged_pr_heads={},
        )
        self.assertEqual([item.name for item in plan.deletions], ["pasi/snapshot"])

    def test_explicit_keeper_is_never_deleted(self) -> None:
        branches = (
            BranchRef("pasi/canonical", "abc"),
            BranchRef("pasi/snapshot", "abc"),
        )
        plan = build_cleanup_plan(
            branches,
            open_pr_heads=frozenset(),
            merged_pr_heads={},
            keep_branches=frozenset({"pasi/snapshot"}),
        )
        self.assertEqual([item.name for item in plan.keepers], ["pasi/snapshot"])
        self.assertEqual([item.name for item in plan.deletions], ["pasi/canonical"])

    def test_superseded_snapshot_is_deletable(self) -> None:
        branches = (
            BranchRef("pasi/feature", "new"),
            BranchRef("pasi/feature-pr", "old"),
        )
        plan = build_cleanup_plan(
            branches,
            open_pr_heads=frozenset(),
            merged_pr_heads={},
            superseded_branches=frozenset({"pasi/feature-pr"}),
        )
        self.assertEqual(
            [item.name for item in plan.deletions],
            ["pasi/feature-pr"],
        )

    def test_kept_canonical_branch_can_supersede_snapshot(self) -> None:
        branches = (
            BranchRef("pasi/feature", "new"),
            BranchRef("pasi/feature-pr", "old"),
        )
        with unittest.mock.patch(
            "scripts.cleanup_duplicate_branches._request_json",
            return_value={"status": "ahead", "ahead_by": 1, "behind_by": 0},
        ):
            superseded = list_superseded_snapshot_branches(
                branches,
                token="test-token",
                open_pr_heads=frozenset(),
                keep_branches=frozenset({"pasi/feature"}),
            )
        self.assertEqual(superseded, frozenset({"pasi/feature-pr"}))

    def test_open_or_kept_superseded_snapshot_is_not_deleted(self) -> None:
        branches = (
            BranchRef("pasi/feature", "new"),
            BranchRef("pasi/feature-pr", "old"),
        )
        plan = build_cleanup_plan(
            branches,
            open_pr_heads=frozenset({"pasi/feature-pr"}),
            merged_pr_heads={},
            superseded_branches=frozenset({"pasi/feature-pr"}),
        )
        self.assertEqual(plan.deletions, ())

    def test_explicit_keeper_survives_fully_merged_pass(self) -> None:
        branches = (BranchRef("pasi/keeper", "abc"),)
        plan = build_cleanup_plan(
            branches,
            open_pr_heads=frozenset(),
            merged_pr_heads={},
            fully_merged_branches=frozenset({"pasi/keeper"}),
            keep_branches=frozenset({"pasi/keeper"}),
        )
        self.assertEqual(plan.deletions, ())

    def test_merged_branch_can_be_deleted_only_when_proven_safe(self) -> None:
        safe = frozenset({"pasi/merged"})
        self.assertTrue(
            can_delete_merged_branch(
                "pasi/merged",
                deletable_branches=safe,
                open_pr_heads=frozenset(),
            )
        )
        self.assertFalse(
            can_delete_merged_branch(
                "pasi/unproven",
                deletable_branches=safe,
                open_pr_heads=frozenset(),
            )
        )
        self.assertFalse(
            can_delete_merged_branch(
                "main",
                deletable_branches=safe,
                open_pr_heads=frozenset(),
            )
        )
        self.assertFalse(
            can_delete_merged_branch(
                "pasi/merged",
                deletable_branches=safe,
                open_pr_heads=frozenset({"pasi/merged"}),
            )
        )

    def test_closed_unmerged_branch_is_not_deleted_without_proof(self) -> None:
        branches = (BranchRef("feature/closed", "feature-tip"),)
        plan = build_cleanup_plan(
            branches,
            open_pr_heads=frozenset(),
            merged_pr_heads={},
        )
        self.assertEqual(plan.deletions, ())


if __name__ == "__main__":
    unittest.main()
