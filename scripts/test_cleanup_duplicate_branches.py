from __future__ import annotations

import unittest
import unittest.mock

from scripts.cleanup_duplicate_branches import (
    BranchRef,
    build_cleanup_plan,
    can_delete_merged_branch,
    is_disposable_name,
    list_superseded_snapshot_branches,
    CANONICAL_KEEP_BRANCHES,
    CANONICAL_KEEP_BRANCH_TIPS,
    missing_canonical_keep_branches,
    restore_missing_canonical_keep_branches,
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
            merged_pr_heads={},
        )
        self.assertEqual([item.name for item in plan.keepers], ["pasi/feature"])
        self.assertEqual(
            {item.name for item in plan.deletions},
            {"pasi/feature-final", "pasi/feature-pr"},
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

    def test_canonical_keep_branches_are_built_in(self) -> None:
        self.assertEqual(
            CANONICAL_KEEP_BRANCHES,
            frozenset(
                {
                    "pasi/bridge-edge-case-tests-20260917",
                    "pasi/control-plane-recovery-20260917",
                    "pasi/continuation-anti-loop-20260918",
                }
            ),
        )

    def test_missing_canonical_keeper_is_detected(self) -> None:
        branches = (
            BranchRef("main", "mainsha"),
            BranchRef("pasi/bridge-edge-case-tests-20260917", "bridge"),
            BranchRef("pasi/control-plane-recovery-20260917", "recovery"),
        )
        self.assertEqual(
            missing_canonical_keep_branches(branches),
            ("pasi/continuation-anti-loop-20260918",),
        )

    def test_present_canonical_keepers_are_not_restored(self) -> None:
        branches = (
            BranchRef(name, sha)
            for name, sha in CANONICAL_KEEP_BRANCH_TIPS.items()
        )
        with unittest.mock.patch(
            "scripts.cleanup_duplicate_branches._create_ref"
        ) as create_ref:
            restored = restore_missing_canonical_keep_branches(
                tuple(branches),
                token="test-token",
            )
        create_ref.assert_not_called()
        self.assertEqual(restored, ())

    def test_missing_canonical_keeper_is_restored_at_known_tip(self) -> None:
        branches = (
            BranchRef("pasi/bridge-edge-case-tests-20260917", "bridge"),
            BranchRef("pasi/control-plane-recovery-20260917", "recovery"),
        )
        with unittest.mock.patch(
            "scripts.cleanup_duplicate_branches._create_ref"
        ) as create_ref:
            restored = restore_missing_canonical_keep_branches(
                branches,
                token="test-token",
            )
        create_ref.assert_called_once_with(
            "pasi/continuation-anti-loop-20260918",
            "0f9047ad6e4e8ca4637372e391faa26ecdb49a85",
            token="test-token",
        )
        self.assertEqual(restored, ("pasi/continuation-anti-loop-20260918",))

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
