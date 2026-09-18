from __future__ import annotations

import unittest

from scripts.cleanup_duplicate_branches import (
    BranchRef,
    build_cleanup_plan,
    can_delete_merged_branch,
    is_disposable_name,
)


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
            merged_pr_heads=frozenset(),
        )
        self.assertEqual([item.name for item in plan.keepers], ["pasi/feature"])
        self.assertEqual(
            {item.name for item in plan.deletions},
            {"pasi/feature-final", "pasi/feature-pr"},
        )

    def test_merged_pr_branch_wins_when_competing_with_noncanonical_snapshot(self) -> None:
        branches = (
            BranchRef("feature/local-byte-storage", "abc"),
            BranchRef("feature/file-service-boundary", "abc"),
            BranchRef("feature/local-byte-storage-final", "abc"),
        )
        plan = build_cleanup_plan(
            branches,
            open_pr_heads=frozenset(),
            merged_pr_heads=frozenset({"feature/local-byte-storage"}),
        )
        self.assertEqual([item.name for item in plan.keepers], ["feature/local-byte-storage"])

    def test_open_pr_head_is_never_deleted(self) -> None:
        branches = (
            BranchRef("pasi/feature", "abc"),
            BranchRef("pasi/feature-pr", "abc"),
        )
        plan = build_cleanup_plan(
            branches,
            open_pr_heads=frozenset({"pasi/feature-pr"}),
            merged_pr_heads=frozenset(),
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
            merged_pr_heads=frozenset(),
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
            merged_pr_heads=frozenset(),
            keep_branches=frozenset({"pasi/snapshot"}),
        )
        self.assertEqual(plan.deletions, ())

    def test_merged_branch_can_be_deleted_only_when_not_open_or_main(self) -> None:
        self.assertTrue(
            can_delete_merged_branch("pasi/merged", open_pr_heads=frozenset())
        )
        self.assertFalse(
            can_delete_merged_branch("main", open_pr_heads=frozenset())
        )
        self.assertFalse(
            can_delete_merged_branch(
                "pasi/merged",
                open_pr_heads=frozenset({"pasi/merged"}),
            )
        )


if __name__ == "__main__":
    unittest.main()
