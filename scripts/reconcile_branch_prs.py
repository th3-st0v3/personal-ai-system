from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from scripts.pasi_promote import classify_risk

MAIN_BRANCH = "main"
AUTO_READY_MARKER = "PASI_AUTO_READY: true"
HYGIENE_MARKER = "PASI_BRANCH_HYGIENE: managed"
PROTECTED_BRANCHES = frozenset({"main", "beta-foundation"})
SYSTEM_MANAGED_PREFIXES = ("dependabot/", "renovate/")
MAX_PR_TITLE_CHARS = 65


class BranchPrReconciliationError(RuntimeError):
    pass


@dataclass(frozen=True)
class PullRequestRecord:
    number: int
    title: str
    body: str
    url: str
    head_branch: str
    head_sha: str
    head_repo: str
    is_draft: bool
    merged_at: str | None
    mergeable: str
    merge_state: str
    changed_paths: tuple[str, ...]
    risk: str
    updated_at: str


@dataclass(frozen=True)
class ReconciliationResult:
    opened_prs: tuple[str, ...] = ()
    reopened_prs: tuple[int, ...] = ()
    ready_prs: tuple[int, ...] = ()
    auto_merge_requested: tuple[int, ...] = ()
    deleted_branches: tuple[str, ...] = ()
    skipped: tuple[str, ...] = ()


def _repository() -> str:
    value = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if "/" not in value:
        raise BranchPrReconciliationError("GITHUB_REPOSITORY must be owner/name")
    return value


def _run(command: Sequence[str], *, timeout: float = 30.0) -> tuple[int, str]:
    try:
        result = subprocess.run(
            list(command),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)
    output = ((result.stdout or "") + (result.stderr or "")).strip()
    return result.returncode, output[-12_000:]


def gh_available() -> bool:
    return shutil.which("gh") is not None


def gh_authenticated() -> bool:
    if not gh_available():
        return False
    code, _ = _run(["gh", "auth", "status"], timeout=15.0)
    return code == 0


def _gh_api_json(path: str, *, paginate: bool = False) -> Any:
    command = ["gh", "api", f"repos/{_repository()}/{path.lstrip('/')}"]
    if paginate:
        command.extend(["--paginate", "--slurp"])
    code, output = _run(command, timeout=60.0)
    if code != 0:
        raise BranchPrReconciliationError(
            f"GitHub API request failed for {path}: {output}"
        )
    try:
        return json.loads(output)
    except json.JSONDecodeError as exc:
        raise BranchPrReconciliationError(
            f"GitHub API returned invalid JSON for {path}"
        ) from exc


def _list_changed_paths(pr_number: int) -> tuple[str, ...]:
    raw_pages = _gh_api_json(f"pulls/{pr_number}/files?per_page=100", paginate=True)
    if not isinstance(raw_pages, list):
        raise BranchPrReconciliationError(
            f"changed-file response was not a list for PR #{pr_number}"
        )
    payload = [item for page in raw_pages if isinstance(page, list) for item in page]
    return tuple(
        sorted(
            {
                str(item.get("filename", "")).strip()
                for item in payload
                if isinstance(item, dict) and str(item.get("filename", "")).strip()
            }
        )
    )


def _pull_request_record(item: Mapping[str, Any]) -> PullRequestRecord | None:
    head = item.get("head")
    head_repo = head.get("repo") if isinstance(head, dict) else None
    if not isinstance(head, dict) or not isinstance(head_repo, dict):
        return None
    branch = str(head.get("ref", "")).strip()
    sha = str(head.get("sha", "")).strip()
    repo_name = str(head_repo.get("full_name", "")).strip()
    if not branch or not sha or not repo_name:
        return None
    try:
        number = int(item.get("number"))
    except (TypeError, ValueError):
        return None
    changed_paths = _list_changed_paths(number)
    return PullRequestRecord(
        number=number,
        title=str(item.get("title", "")),
        body=str(item.get("body", "") or ""),
        url=str(item.get("html_url", "")),
        head_branch=branch,
        head_sha=sha,
        head_repo=repo_name,
        is_draft=bool(item.get("draft", False)),
        merged_at=str(item.get("merged_at")) if item.get("merged_at") else None,
        mergeable=str(item.get("mergeable", "") or "").upper(),
        merge_state=str(item.get("mergeable_state", "") or "").upper(),
        changed_paths=changed_paths,
        risk=classify_risk(changed_paths),
        updated_at=str(item.get("updated_at", "") or ""),
    )


def list_open_pull_requests() -> tuple[PullRequestRecord, ...]:
    raw_pages = _gh_api_json("pulls?state=open&per_page=100", paginate=True)
    if not isinstance(raw_pages, list):
        raise BranchPrReconciliationError("open pull-request response was not a list")
    payload = [item for page in raw_pages if isinstance(page, list) for item in page]
    records = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        record = _pull_request_record(item)
        if record is not None:
            records.append(record)
    return tuple(records)


def list_closed_pull_requests() -> tuple[PullRequestRecord, ...]:
    raw_pages = _gh_api_json("pulls?state=closed&per_page=100", paginate=True)
    if not isinstance(raw_pages, list):
        raise BranchPrReconciliationError("closed pull-request response was not a list")
    payload = [item for page in raw_pages if isinstance(page, list) for item in page]
    records = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        record = _pull_request_record(item)
        if record is not None:
            records.append(record)
    return tuple(records)


def _checks_green(pr_number: int) -> tuple[bool, str]:
    code, output = _run(
        [
            "gh",
            "pr",
            "checks",
            str(pr_number),
            "--json",
            "name,bucket,workflow,event",
        ],
        timeout=45.0,
    )
    try:
        payload = json.loads(output or "[]")
    except json.JSONDecodeError:
        return False, "GitHub checks did not return parseable JSON"
    if not isinstance(payload, list) or not payload:
        return False, "no GitHub checks are currently reported"
    failures = []
    pending = []
    for check in payload:
        if not isinstance(check, dict):
            return False, "GitHub returned a malformed check record"
        bucket = str(check.get("bucket", "unknown"))
        if bucket == "pass":
            continue
        if bucket in {"pending", "skipping"}:
            pending.append(f"{check.get('name', 'unnamed')}: {bucket}")
        else:
            failures.append(f"{check.get('name', 'unnamed')}: {bucket}")
    if code != 0 or failures or pending:
        detail = ", ".join((failures + pending)[:10]) or f"gh pr checks exited with {code}"
        return False, detail
    return True, f"all {len(payload)} reported checks passed"


def _compare_branch(branch: str) -> dict[str, Any] | None:
    code, output = _run(
        ["gh", "api", f"repos/{_repository()}/compare/{MAIN_BRANCH}...{branch}"],
        timeout=30.0,
    )
    if code != 0:
        return None
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _branch_ahead(branch: str) -> int | None:
    compare = _compare_branch(branch)
    if compare is None:
        return None
    value = compare.get("ahead_by")
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def is_auto_ready_authorized(pr: PullRequestRecord) -> bool:
    normalized = re.sub(r"\s+", " ", pr.body).casefold()
    return (
        AUTO_READY_MARKER.casefold() in normalized
        or HYGIENE_MARKER.casefold() in normalized
    )


def is_merge_candidate(pr: PullRequestRecord, *, checks_green: bool) -> bool:
    return (
        pr.head_repo == _repository()
        and not pr.is_draft
        and pr.risk == "standard"
        and pr.mergeable == "MERGEABLE"
        and pr.merge_state in {"CLEAN", "HAS_HOOKS"}
        and checks_green
    )


def is_hygiene_managed_draft_candidate(pr: PullRequestRecord, *, checks_green: bool) -> bool:
    return (
        pr.head_repo == _repository()
        and pr.is_draft
        and pr.risk == "standard"
        and pr.mergeable == "MERGEABLE"
        and pr.merge_state in {"CLEAN", "HAS_HOOKS"}
        and checks_green
        and is_auto_ready_authorized(pr)
    )


def _create_draft_pr(branch: str) -> str:
    title = f"Draft: {branch}"[:MAX_PR_TITLE_CHARS]
    body = (
        "## PASI branch hygiene\n\n"
        "Branch hygiene opened this draft because the branch contains work not represented "
        "by an open pull request. It is kept visible and reviewable until its current head "
        "has an authoritative passing check set.\n\n"
        f"Branch: {branch}\n\n"
        f"{AUTO_READY_MARKER}\n"
        f"{HYGIENE_MARKER}\n"
        "The repository's required reviews, checks, and branch protections remain authoritative."
    )
    code, output = _run(
        [
            "gh",
            "pr",
            "create",
            "--base",
            MAIN_BRANCH,
            "--head",
            branch,
            "--draft",
            "--title",
            title,
            "--body",
            body,
        ],
        timeout=45.0,
    )
    if code != 0:
        raise BranchPrReconciliationError(
            f"could not open draft PR for {branch}: {output}"
        )
    return output.splitlines()[-1].strip() if output else branch


def _reopen_pr(pr_number: int) -> bool:
    code, _ = _run(["gh", "pr", "reopen", str(pr_number)], timeout=45.0)
    return code == 0


def _delete_branch(branch: str) -> bool:
    code, _ = _run(
        ["gh", "api", "--method", "DELETE", f"repos/{_repository()}/git/refs/heads/{branch}"],
        timeout=30.0,
    )
    return code == 0


def _is_protected_or_managed(branch: str) -> bool:
    return (
        branch in PROTECTED_BRANCHES
        or any(branch.startswith(prefix) for prefix in SYSTEM_MANAGED_PREFIXES)
    )


def _closed_pr_index(prs: Sequence[PullRequestRecord]) -> dict[str, PullRequestRecord]:
    by_branch: dict[str, PullRequestRecord] = {}
    for pr in prs:
        if pr.head_repo != _repository():
            continue
        existing = by_branch.get(pr.head_branch)
        if existing is None or pr.updated_at > existing.updated_at:
            by_branch[pr.head_branch] = pr
    return by_branch


def reconcile_branches(
    branches: Sequence[Mapping[str, Any]],
    open_prs: Sequence[PullRequestRecord],
    closed_prs: Sequence[PullRequestRecord],
) -> ReconciliationResult:
    open_heads = frozenset(
        pr.head_branch for pr in open_prs if pr.head_repo == _repository()
    )
    closed_index = _closed_pr_index(closed_prs)
    opened: list[str] = []
    reopened: list[int] = []
    deleted: list[str] = []
    skipped: list[str] = []

    for branch_info in branches:
        branch = str(branch_info.get("name", "")).strip()
        if not branch or _is_protected_or_managed(branch):
            continue

        ahead = _branch_ahead(branch)
        if ahead is None:
            skipped.append(f"{branch}: unable to compare branch with {MAIN_BRANCH}")
            continue

        if branch in open_heads:
            continue

        closed = closed_index.get(branch)
        if ahead <= 0:
            if closed and closed.merged_at:
                reason = "merged PR has no unique branch work"
            elif closed:
                reason = "closed PR has no unique branch work"
            else:
                reason = "branch has no unique commits beyond main"
            if _delete_branch(branch):
                deleted.append(branch)
            else:
                skipped.append(f"{branch}: delete refused or failed ({reason})")
            continue

        if closed and not closed.merged_at:
            if _reopen_pr(closed.number):
                reopened.append(closed.number)
            else:
                skipped.append(f"{branch}: closed PR #{closed.number} still contains unique work but could not be reopened")
            continue

        try:
            _create_draft_pr(branch)
            opened.append(branch)
        except BranchPrReconciliationError as exc:
            skipped.append(f"{branch}: {exc}")

    return ReconciliationResult(
        opened_prs=tuple(opened),
        reopened_prs=tuple(reopened),
        deleted_branches=tuple(deleted),
        skipped=tuple(skipped),
    )


def reconcile_open_pull_requests(
    prs: Sequence[PullRequestRecord],
) -> tuple[tuple[int, ...], tuple[int, ...], tuple[str, ...]]:
    ready: list[int] = []
    merged: list[int] = []
    skipped: list[str] = []

    for pr in prs:
        if pr.head_repo != _repository():
            skipped.append(f"PR #{pr.number}: fork-owned head")
            continue

        checks_ok, checks_message = _checks_green(pr.number)

        if is_hygiene_managed_draft_candidate(pr, checks_green=checks_ok):
            code, output = _run(["gh", "pr", "ready", str(pr.number)], timeout=30.0)
            if code != 0:
                skipped.append(f"PR #{pr.number}: could not convert draft to ready: {output[-500:]}")
                continue
            ready.append(pr.number)
            code, output = _run(
                ["gh", "pr", "merge", str(pr.number), "--squash", "--auto", "--delete-branch"],
                timeout=45.0,
            )
            if code == 0:
                merged.append(pr.number)
            else:
                skipped.append(f"PR #{pr.number}: ready but merge request not accepted: {output[-500:]}")
            continue

        if is_merge_candidate(pr, checks_green=checks_ok):
            code, output = _run(
                ["gh", "pr", "merge", str(pr.number), "--squash", "--auto", "--delete-branch"],
                timeout=45.0,
            )
            if code == 0:
                merged.append(pr.number)
            else:
                skipped.append(f"PR #{pr.number}: checks passed but merge request not accepted: {output[-500:]}")
            continue

        skipped.append(
            f"PR #{pr.number}: no action (risk={pr.risk}, draft={pr.is_draft}, "
            f"mergeable={pr.mergeable}, merge_state={pr.merge_state}, checks={checks_message})"
        )

    return tuple(ready), tuple(merged), tuple(skipped)


def list_branches() -> tuple[dict[str, Any], ...]:
    raw_pages = _gh_api_json("branches?per_page=100", paginate=True)
    if not isinstance(raw_pages, list):
        raise BranchPrReconciliationError("branches response was not a list")
    payload = [item for page in raw_pages if isinstance(page, list) for item in page]
    return tuple(item for item in payload if isinstance(item, dict))


def reconcile(*, json_output: bool = False) -> ReconciliationResult:
    if not gh_available() or not gh_authenticated():
        raise BranchPrReconciliationError(
            "GitHub CLI is required and must be authenticated for branch reconciliation"
        )

    branches = list_branches()
    open_prs = list_open_pull_requests()
    closed_prs = list_closed_pull_requests()

    branch_result = reconcile_branches(branches, open_prs, closed_prs)

    # Re-read after branch opens/reopens so the merge pass sees the authoritative current PR set.
    current_prs = list_open_pull_requests()
    ready, merged, skipped = reconcile_open_pull_requests(current_prs)

    result = ReconciliationResult(
        opened_prs=branch_result.opened_prs,
        reopened_prs=branch_result.reopened_prs,
        ready_prs=ready,
        auto_merge_requested=merged,
        deleted_branches=branch_result.deleted_branches,
        skipped=tuple(branch_result.skipped) + tuple(skipped),
    )
    payload = {
        "opened_prs": list(result.opened_prs),
        "reopened_prs": list(result.reopened_prs),
        "ready_prs": list(result.ready_prs),
        "auto_merge_requested": list(result.auto_merge_requested),
        "deleted_branches": list(result.deleted_branches),
        "skipped": list(result.skipped),
        "policy": {
            "passed_head": "observe current checks; do not rerun passed checks",
            "failed_head": "do not merge; a new synchronize/push supplies the next test head",
            "closed_pr": "delete branch when no unique work remains; reopen when unique work remains",
            "open_pr": "merge when current checks pass and GitHub reports a mergeable eligible PR",
        },
    }
    if json_output:
        print(json.dumps(payload, indent=2))
    else:
        print(
            "PASI branch/PR reconciliation: "
            f"opened={len(result.opened_prs)} "
            f"reopened={len(result.reopened_prs)} "
            f"ready={len(result.ready_prs)} "
            f"merged={len(result.auto_merge_requested)} "
            f"deleted={len(result.deleted_branches)}"
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Repository-wide branch and pull-request reconciliation."
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        reconcile(json_output=args.json)
    except BranchPrReconciliationError as exc:
        print(f"branch/PR reconciliation failed: {exc}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
