# PASI Branch Hygiene

## Coverage

The branch-hygiene workflow is a repository-wide lifecycle process. It runs on branch pushes, pull-request lifecycle events, completion of the authoritative test workflow, a daily schedule, and manual dispatch.

## Branch cleanup

Existing cleanup only removes refs that are proven redundant: merged PR heads, branches fully contained in main, duplicate/snapshot refs covered by the cleanup policy, or other explicitly disposable refs. The default branch, active PR heads, and explicit keepers are preserved.

A closed PR does not by itself prove that its branch is disposable; unmerged work is retained unless the existing cleanup proof establishes that the ref is redundant.

## Pull-request reconciliation

An ahead-of-main branch without an open PR receives a draft PR so work remains visible and reviewable instead of becoming an orphaned branch.

Ready, same-repository, standard-risk PRs are eligible for automatic squash auto-merge only when GitHub reports them mergeable and all currently reported checks pass. Required reviews and branch-protection rules remain authoritative and can still block the merge.

Draft PRs remain drafts unless their description explicitly contains PASI_AUTO_MERGE: true or PASI_AUTO_READY: true. An authorized draft is converted to ready only after it is standard-risk, mergeable, and green, then automatic squash merge is requested.

High-risk changes—including controller, browser, security-boundary, provider-routing, workflow, and other protected automation paths classified by scripts/pasi_promote.py—are never auto-merged by branch hygiene.

Fork-owned PRs are never mutated by the branch-hygiene workflow.

## Future branches

Because the workflow receives all branch pushes and also runs on a schedule, a newly created work branch does not require a special branch-name registration to enter the hygiene lifecycle. System-managed dependency branches such as Dependabot and Renovate remain outside the orphan-PR creation path.

## Safety

Branch hygiene never force-merges, bypasses reviews, rewrites another open PR's branch, marks incomplete work complete, or deletes an active PR head.

Write-capable workflow-run execution is restricted to runs whose head repository is this repository, preventing untrusted fork code from running with repository write permissions.

## Operational principle

The goal is not maximum deletion or maximum merging. The goal is a continuously reconciled repository in which active work has a visible PR, completed work does not leave unnecessary refs behind, and protected/high-risk work remains subject to normal human review.