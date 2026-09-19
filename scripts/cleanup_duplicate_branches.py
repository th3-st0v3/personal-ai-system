from __future__ import annotations

import argparse
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Iterable, Mapping

API_VERSION = "2022-11-28"
DEFAULT_BRANCH = "main"
DISPOSABLE_SUFFIX_RE = re.compile(
    r"(?:-pr\d*|-final\d*|-v\d+|-head|-verified|-check\d*|-current|-submit|-merge)$",
    re.IGNORECASE,
)


class BranchCleanupError(RuntimeError):
    pass


@dataclass(frozen=True)
class BranchRef:
    name: str
    sha: str


@dataclass(frozen=True)
class CleanupPlan:
    keepers: tuple[BranchRef, ...]
    deletions: tuple[BranchRef, ...]
    merged_branch: str = ""


def _repository() -> str:
    value = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if "/" not in value:
        raise BranchCleanupError("GITHUB_REPOSITORY must be set to owner/name")
    return value


def _token() -> str:
    value = os.environ.get("GITHUB_TOKEN", "").strip() or os.environ.get("GH_TOKEN", "").strip()
    if not value:
        raise BranchCleanupError("GITHUB_TOKEN or GH_TOKEN must be set")
    return value


def _request_json(path: str, *, token: str) -> object:
    request = urllib.request.Request(
        f"https://api.github.com/repos/{_repository()}/{path.lstrip('/')}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": API_VERSION,
            "User-Agent": "pasi-branch-hygiene",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
        raise BranchCleanupError(f"GitHub API request failed for {path}: {exc}") from exc


def _delete_ref(branch: str, *, token: str) -> None:
    encoded_branch = urllib.parse.quote(branch, safe="/")
    path = f"git/refs/heads/{encoded_branch}"
    request = urllib.request.Request(
        f"https://api.github.com/repos/{_repository()}/{path}",
        method="DELETE",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": API_VERSION,
            "User-Agent": "pasi-branch-hygiene",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30):
            return
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return
        raise BranchCleanupError(f"could not delete branch {branch}: HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise BranchCleanupError(f"could not delete branch {branch}: {exc}") from exc


def list_branches(*, token: str) -> tuple[BranchRef, ...]:
    branches: list[BranchRef] = []
    page = 1
    while True:
        payload = _request_json(f"branches?per_page=100&page={page}", token=token)
        if not isinstance(payload, list):
            raise BranchCleanupError("GitHub branches response was not a list")
        for item in payload:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            commit = item.get("commit")
            sha = str(commit.get("sha", "")).strip() if isinstance(commit, dict) else ""
            if name and sha:
                branches.append(BranchRef(name, sha))
        if len(payload) < 100:
            break
        page += 1
    return tuple(branches)


def _list_merged_pr_head_shas_for_branches(
    branches: Iterable[BranchRef],
    *,
    token: str,
) -> Mapping[str, frozenset[str]]:
    """Return merged PR head SHAs associated with each surviving branch tip.

    The commit-to-pull-requests endpoint directly associates the current branch
    tip with its merged PRs, which handles squash merges and reused branch names.
    """
    heads: dict[str, set[str]] = {}
    for branch in branches:
        encoded_sha = urllib.parse.quote(branch.sha, safe="")
        payload = _request_json(
            f"commits/{encoded_sha}/pulls?per_page=100",
            token=token,
        )
        if not isinstance(payload, list):
            raise BranchCleanupError(
                f"GitHub pull-request association response was not a list for {branch.name}"
            )
        for item in payload:
            if not isinstance(item, dict) or not item.get("merged_at"):
                continue
            head = item.get("head")
            if not isinstance(head, dict):
                continue
            ref = str(head.get("ref", "")).strip()
            sha = str(head.get("sha", "")).strip()
            head_repo = head.get("repo")
            repo_name = (
                str(head_repo.get("full_name", "")).strip()
                if isinstance(head_repo, dict)
                else ""
            )
            if repo_name and repo_name != _repository():
                continue
            if ref == branch.name and sha:
                heads.setdefault(ref, set()).add(sha)
    return {name: frozenset(shas) for name, shas in heads.items()}


def list_branches_fully_merged_into_default(
    branches: Iterable[BranchRef],
    *,
    token: str,
    open_pr_heads: frozenset[str],
    keep_branches: frozenset[str],
    default_branch: str = DEFAULT_BRANCH,
) -> frozenset[str]:
    merged: set[str] = set()
    for branch in branches:
        if (
            branch.name == default_branch
            or branch.name in open_pr_heads
            or branch.name in keep_branches
        ):
            continue
        encoded_branch = urllib.parse.quote(branch.name, safe="")
        encoded_base = urllib.parse.quote(default_branch, safe="")
        payload = _request_json(
            f"compare/{encoded_base}...{encoded_branch}",
            token=token,
        )
        if not isinstance(payload, dict):
            raise BranchCleanupError(
                f"GitHub compare response was not an object for {branch.name}"
            )
        ahead_by = payload.get("ahead_by")
        status = payload.get("status")
        if isinstance(ahead_by, bool) or not isinstance(ahead_by, int):
            raise BranchCleanupError(
                f"GitHub compare response lacked a valid ahead_by for {branch.name}"
            )
        # ahead_by == 0 means the branch tip is identical to or contained in
        # default_branch. Deleting the ref cannot remove its commits from main.
        if ahead_by == 0 and status in {"behind", "identical"}:
            merged.add(branch.name)
    return frozenset(merged)


def list_open_pr_heads(*, token: str) -> frozenset[str]:
    heads: set[str] = set()
    page = 1
    while True:
        payload = _request_json(
            f"pulls?state=open&per_page=100&page={page}",
            token=token,
        )
        if not isinstance(payload, list):
            raise BranchCleanupError("GitHub pull-request response was not a list")
        for item in payload:
            if not isinstance(item, dict):
                continue
            head = item.get("head")
            if isinstance(head, dict):
                ref = str(head.get("ref", "")).strip()
                if ref:
                    heads.add(ref)
        if len(payload) < 100:
            break
        page += 1
    return frozenset(heads)


def is_disposable_name(branch_name: str) -> bool:
    return bool(DISPOSABLE_SUFFIX_RE.search(branch_name.rstrip("/")))


def _keeper_key(branch: BranchRef) -> tuple[int, int, str]:
    return (
        1 if not is_disposable_name(branch.name) else 0,
        -len(branch.name),
        branch.name,
    )


def list_superseded_snapshot_branches(
    branches: Iterable[BranchRef],
    *,
    token: str,
    open_pr_heads: frozenset[str],
    keep_branches: frozenset[str],
    default_branch: str = DEFAULT_BRANCH,
) -> frozenset[str]:
    """Find disposable suffix branches whose unsuffixed sibling contains their tip.

    The deletion is only considered safe when the sibling branch is a real,
    non-disposable ref and GitHub proves the candidate is an ancestor of it.
    """
    branch_by_name = {branch.name: branch for branch in branches}
    superseded: set[str] = set()
    for branch in branches:
        if (
            branch.name == default_branch
            or branch.name in open_pr_heads
            or branch.name in keep_branches
            or not is_disposable_name(branch.name)
        ):
            continue
        match = DISPOSABLE_SUFFIX_RE.search(branch.name.rstrip("/"))
        if match is None:
            continue
        canonical_name = branch.name[: match.start()].rstrip("-/")
        canonical = branch_by_name.get(canonical_name)
        if (
            canonical is None
            or canonical.name == default_branch
            or canonical.name in open_pr_heads
            or is_disposable_name(canonical.name)
        ):
            continue
        encoded_branch = urllib.parse.quote(branch.name, safe="")
        encoded_canonical = urllib.parse.quote(canonical.name, safe="")
        payload = _request_json(
            f"compare/{encoded_branch}...{encoded_canonical}",
            token=token,
        )
        if not isinstance(payload, dict):
            raise BranchCleanupError(
                f"GitHub compare response was not an object for {branch.name}"
            )
        ahead_by = payload.get("ahead_by")
        behind_by = payload.get("behind_by")
        status = payload.get("status")
        if (
            isinstance(ahead_by, int)
            and not isinstance(ahead_by, bool)
            and isinstance(behind_by, int)
            and not isinstance(behind_by, bool)
            and status == "ahead"
            and ahead_by > 0
            and behind_by == 0
        ):
            superseded.add(branch.name)
    return frozenset(superseded)


def build_cleanup_plan(
    branches: Iterable[BranchRef],
    *,
    open_pr_heads: frozenset[str],
    merged_pr_heads: Mapping[str, frozenset[str]],
    fully_merged_branches: frozenset[str] = frozenset(),
    superseded_branches: frozenset[str] = frozenset(),
    default_branch: str = DEFAULT_BRANCH,
    keep_branches: frozenset[str] = frozenset(),
) -> CleanupPlan:
    grouped: dict[str, list[BranchRef]] = {}
    branch_by_name = {}
    for branch in branches:
        grouped.setdefault(branch.sha, []).append(branch)
        branch_by_name[branch.name] = branch

    keep: dict[str, BranchRef] = {}
    deletions: dict[str, BranchRef] = {}

    for group in grouped.values():
        if len(group) < 2:
            continue

        eligible = [
            branch
            for branch in group
            if branch.name != default_branch
            and branch.name not in open_pr_heads
            and branch.name not in keep_branches
        ]
        if not eligible:
            continue

        protected_keepers = [
            branch
            for branch in group
            if branch.name in keep_branches
            or branch.name == default_branch
            or branch.name in open_pr_heads
        ]
        keeper = (
            sorted(protected_keepers, key=lambda item: item.name)[0]
            if protected_keepers
            else max(eligible, key=_keeper_key)
        )
        keep[keeper.name] = keeper

        for branch in group:
            if branch.name == keeper.name:
                continue
            if branch.name == default_branch or branch.name in open_pr_heads or branch.name in keep_branches:
                continue
            deletions[branch.name] = branch

    # A disposable snapshot whose tip is fully contained in its canonical
    # unsuffixed sibling is redundant even when neither branch is contained in main.
    for branch_name in superseded_branches:
        branch = branch_by_name.get(branch_name)
        if branch is None:
            continue
        if branch_name == default_branch or branch_name in open_pr_heads or branch_name in keep_branches:
            continue
        if branch_name in keep:
            continue
        deletions.setdefault(branch_name, branch)

    # A branch whose current tip is exactly the head commit of a merged PR has
    # no newer work on that ref. It can be removed safely unless it is explicitly
    # kept, is main, or currently backs another open PR. A branch that advanced
    # after merge is not deleted.
    for branch_name, merged_shas in merged_pr_heads.items():
        branch = branch_by_name.get(branch_name)
        if branch is None:
            continue
        if branch_name in keep or branch_name in keep_branches:
            continue
        if branch_name == default_branch or branch_name in open_pr_heads:
            continue
        if branch.sha in merged_shas:
            deletions.setdefault(branch_name, branch)

    # A branch tip already contained in main is safe to remove even when the
    # branch did not come from a merged PR, because its commits remain reachable
    # from main after the ref is deleted.
    for branch_name in fully_merged_branches:
        branch = branch_by_name.get(branch_name)
        if branch is None:
            continue
        if (
            branch_name == default_branch
            or branch_name in open_pr_heads
            or branch_name in keep_branches
            or branch_name in keep
        ):
            continue
        deletions.setdefault(branch_name, branch)

    deletions_tuple = tuple(sorted(deletions.values(), key=lambda item: (item.name, item.sha)))
    keepers = tuple(sorted(keep.values(), key=lambda item: item.name))
    return CleanupPlan(keepers=keepers, deletions=deletions_tuple)


def can_delete_merged_branch(
    branch: str,
    *,
    deletable_branches: frozenset[str],
    open_pr_heads: frozenset[str],
    default_branch: str = DEFAULT_BRANCH,
) -> bool:
    return (
        bool(branch)
        and branch in deletable_branches
        and branch != default_branch
        and branch not in open_pr_heads
    )


def cleanup(
    *,
    dry_run: bool = False,
    keep_branches: frozenset[str] = frozenset(),
    merged_branch: str = "",
) -> CleanupPlan:
    token = _token()
    effective_keep_branches = frozenset(keep_branches)
    branches = list_branches(token=token)
    open_heads = list_open_pr_heads(token=token)
    merged_heads = _list_merged_pr_head_shas_for_branches(
        branches,
        token=token,
    )
    fully_merged = list_branches_fully_merged_into_default(
        branches,
        token=token,
        open_pr_heads=open_heads,
        keep_branches=effective_keep_branches,
    )
    superseded = list_superseded_snapshot_branches(
        branches,
        token=token,
        open_pr_heads=open_heads,
        keep_branches=effective_keep_branches,
    )
    plan = build_cleanup_plan(
        branches,
        open_pr_heads=open_heads,
        merged_pr_heads=merged_heads,
        fully_merged_branches=fully_merged,
        superseded_branches=superseded,
        keep_branches=effective_keep_branches,
    )
    deletable_branches = frozenset(item.name for item in plan.deletions)
    merged_to_delete = (
        merged_branch
        if can_delete_merged_branch(
            merged_branch,
            deletable_branches=deletable_branches,
            open_pr_heads=open_heads,
        )
        else ""
    )
    if not dry_run:
        for branch in plan.deletions:
            _delete_ref(branch.name, token=token)
        if merged_to_delete and merged_to_delete not in {item.name for item in plan.deletions}:
            _delete_ref(merged_to_delete, token=token)
    return CleanupPlan(
        keepers=plan.keepers,
        deletions=plan.deletions,
        merged_branch=merged_to_delete,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Delete safe duplicate and closed-PR branch refs while preserving main, open PR heads, and explicitly kept branches."
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--keep", action="append", default=[])
    parser.add_argument("--merged-branch", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        plan = cleanup(
            dry_run=args.dry_run,
            keep_branches=frozenset(args.keep),
            merged_branch=args.merged_branch,
        )
    except BranchCleanupError as exc:
        print(f"branch cleanup failed: {exc}")
        return 1

    selected = [{"name": item.name, "sha": item.sha} for item in plan.deletions]
    if plan.merged_branch and plan.merged_branch not in {item["name"] for item in selected}:
        selected.append({"name": plan.merged_branch, "sha": "merged-pr-head"})
    deleted = [] if args.dry_run else selected

    payload = {
        "dry_run": args.dry_run,
        "keepers": [{"name": item.name, "sha": item.sha} for item in plan.keepers],
        "selected": selected,
        "deleted": deleted,
        "selected_count": len(selected),
        "deleted_count": len(deleted),
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        mode = "DRY-RUN" if args.dry_run else "APPLIED"
        print(f"PASI branch cleanup {mode}: {len(selected)} branch refs selected")
        for item in selected:
            print(f"  delete {item['name']} ({item['sha']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
