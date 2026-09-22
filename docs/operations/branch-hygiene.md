# PASI Branch Hygiene

## Coverage

The branch-hygiene workflow is a **single repository-wide reconciler**, not a workflow that must be configured once per branch.

It runs from one workflow definition on:
+ pull-request close/ready-for-review lifecycle events;
+ completion of the authoritative `test` workflow;
- the daily schedule;
- manual dispatch.

The authoritative `test` workflow also runs on **every branch and every pull request**, and uses the PASI self-hosted `linux/x64/pasi-wsl` runner. There are no GitHub-hosted `ubuntu-*` runners in the PASI CI/audit workflows.

## State reconciliation

For the current branch/PR head, hygiene observes the existing GitHub check state. It does not launch another copy of a test that already passed.

The intended state machine is:

`current head -> observe checks -> act on current state`

- **Passed:** do not rerun the same head. A passing eligible PR can proceed to merge.
- **Failed:** do not repeatedly rerun the failed head. The engineering/patch cycle produces a new commit; the all-branch `test` workflow then validates that new head.
- **Pending:** leave the PR/branch untouched until the current validation completes.
- **Open + eligible to merge:** request squash auto-merge. Required reviews and branch protection remain authoritative.
- **Closed + no unique work beyond main:** delete the unnecessary branch ref.
- **Closed + unique unmerged work:** reopen the existing PR.
- **Merged + unique post-merge work:** create a new draft PR for the new branch work.
- **Branch with unique work + no PR:** create a draft PR so the work is never orphaned.

## Branch cleanup

The reconciler compares each non-protected branch against `main`. A branch with no commits unique beyond `main` can be deleted when it is not an active PR head and is not a system-managed dependency branch.

The existing proven-safe duplicate cleanup remains in place. The default branch, active PR heads, Dependabot/Renovate refs, and explicit keepers remain protected.

## Pull-request reconciliation

Ready, same-repository, standard-risk PRs are eligible for automatic squash auto-merge only when GitHub reports them mergeable and the current reported checks pass.

Draft PRs created by branch hygiene carry explicit machine-readable markers. Once their current head is green and mergeable, hygiene may convert them to ready and request squash auto-merge.

High-risk changes—including controller, browser, security-boundary, provider-routing, workflow, and other protected automation paths classified by `scripts/pasi_promote.py`—remain outside automatic merging.

Fork-owned PRs are never mutated.

## Future branches

No branch name needs to be added to the workflow. The all-branch `test` workflow provides validation coverage, and its completion triggers repository-wide reconciliation.

A newly created branch enters the lifecycle when its all-branch `test` run completes and is also picked up by the scheduled repository-wide sweep, so stale existing branches do not require a separate manual workflow run per branch.

## Safety

Branch hygiene never force-merges, bypasses required reviews, rewrites another open PR's branch, marks incomplete work complete, or deletes an active PR head.

Write-capable `workflow_run` execution is restricted to same-repository heads. The workflow checks the authoritative current GitHub state before every mutation.

## Operational principle

The objective is a continuously reconciled repository: active work has a visible PR, completed work does not leave unnecessary refs behind, failed heads are not spam-rerun, and protected/high-risk work retains the normal review boundary.
