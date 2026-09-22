from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any, Sequence

from scripts.pasi_promote import classify_risk

MAIN_BRANCH = "main"
AUTO_MERGE_MARKER = "PASI_AUTO_MERGE: true"
AUTO_READY_MARKER = "PASI_AUTO_READY: true"
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
    mergeable: str
    merge_state: str
    changed_paths: tuple[str, ...]
    risk: str


@dataclass(frozen=True)
class ReconciliationResult:
    opened_drafts: tuple[str, ...] = ()
    readied_drafts: tuple[int, ...] = ()
    auto_merge_requested: tuple[int, ...] = ()
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
    command = ["gh", "api", f"repos/{_repository()}/{path.lstrip('/')}" ]
    if paginate:
        command.append("--paginate")
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
    payload = _gh_api_json(f"pulls/{pr_number}/files?per_page=100")
    if not isinstance(payload, list):
        raise BranchPrReconciliationError(
            f"changed-file response was not a list for PR #{pr_number}"
        )
    return tuple(
        sorted(
            {
                str(item.get("filename", "")).strip()
                for item in payload
                if isinstance(item, dict) and str(item.get("filename", "")).strip()
            }
        )
    )


def list_open_pull_requests() -> tuple[PullRequestRecord, ...]:
    payload = _gh_api_json("pulls?state=open&per_page=100")
    if not isinstance(payload, list):
        raise BranchPrReconciliationError("open pull-request response was not a list")

    records: list[PullRequestRecord] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        head = item.get("head")
        head_repo = head.get("repo") if isinstance(head, dict) else None
        if not isinstance(head, dict) or not isinstance(head_repo, dict):
            continue
        branch = str(head.get("ref", "")).strip()
        sha = str(head.get("sha", "")).strip()
        repo_name = str(head_repo.get("full_name", "")).strip()
        if not branch or not sha or not repo_name:
            continue
        try:
            number = int(item.get("number"))
        except (TypeError, ValueError):
            continue
        changed_paths = _list_changed_paths(number)
        records.append(
            PullRequestRecord(
                number=number,
                title=str(item.get("title", "")),
                body=str(item.get("body", "") or ""),
                url=str(item.get("html_url", "")),
                head_branch=branch,
                head_sha=sha,
                head_repo=repo_name,
                is_draft=bool(item.get("draft", False)),
                mergeable=str(item.get("mergeable", "") or ""),
                merge_state=str(item.get("mergeable_state", "") or ""),
                changed_paths=changed_paths,
                risk=classify_risk(changed_paths),
            )
        )
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
    for check in payload:
        if not isinstance(check, dict):
            return False, "GitHub returned a malformed check record"
        if check.get("bucket") != "pass":
            failures.append(
                f"{check.get('name', 'unnamed')}: {check.get('bucket', 'unknown')}"
            )
    if code != 0 or failures:
        detail = ", ".join(failures[:10]) or f"gh pr checks exited with {code}"
        return False, detail
    return True, f"all {len(payload)} reported checks passed"


def is_auto_ready_authorized(body: str) -> bool:
    normalized = re.sub(r"\s+", " ", body).casefold()
    return (
        AUTO_MERGE_MARKER.casefold() in normalized
        or AUTO_READY_MARKER.casefold() in normalized
    )


def is_standard_auto_merge_candidate(pr: PullRequestRecord, *, checks_green: bool) -> bool:
    return (
        pr.head_repo == _repository()
        and not pr.is_draft
        and pr.risk == "standard"
        and pr.mergeable == "MERGEABLE"
        and pr.merge_state in {"CLEAN", "HAS_HOOKS"}
        and checks_green
    )


def should_ready_and_merge_draft(pr: PullRequestRecord, *, checks_green: bool) -> bool:
    return (
        pr.head_repo == _repository()
        and pr.is_draft
        and pr.risk == "standard"
        and pr.mergeable == "MERGEABLE"
        and pr.merge_state in {"CLEAN", "HAS_HOOKS"}
        and checks_green
        and is_auto_ready_authorized(pr.body)
    )


def _create_draft_pr(branch: str) -> str:
    title = f"Draft: {branch}"[:MAX_PR_TITLE_CHARS]
    body = (
        "## PASI branch hygiene\n\n"
        "This branch contains commits without an open pull request. "
        "Branch hygiene opened this draft PR so the work remains visible and reviewable.\n\n"
        f"Branch: {branch}\n\n"
        "This PR remains a draft by default. To authorize automatic readiness and "
        "standard-risk auto-merge, add the exact marker PASI_AUTO_MERGE: true "
        "to this PR description. High-risk/protected changes remain human-review gated."
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


def list_branches_ahead_of_main() -> tuple[dict[str, Any], ...]:
    payload = _gh_api_json("branches?per_page=100")
    if not isinstance(payload, list):
        raise BranchPrReconciliationError("branches response was not a list")

    results: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        code, output = _run(
            ["gh", "api", f"repos/{_repository()}/compare/{MAIN_BRANCH}...{name}"],
            timeout=30.0,
        )
        if code != 0:
            continue
        try:
            compare = json.loads(output)
        except json.JSONDecodeError:
            continue
        if not isinstance(compare, dict):
            continue
        ahead_by = compare.get("ahead_by")
        if isinstance(ahead_by, bool):
            continue
        try:
            ahead = int(ahead_by)
        except (TypeError, ValueError):
            continue
        results.append({"name": name, "ahead_by": ahead})
    return tuple(results)


def open_missing_branch_prs(
    branches: Sequence[Mapping[str, Any]],
    open_head_branches: frozenset[str],
) -> tuple[str, ...]:
    opened: list[str] = []
    for branch in branches:
        name = str(branch.get("name", "")).strip()
        if (
            not name
            or name in PROTECTED_BRANCHES
            or name in open_head_branches
            or any(name.startswith(prefix) for prefix in SYSTEM_MANAGED_PREFIXES)
        ):
            continue
        try:
            ahead_by = int(branch.get("ahead_by"))
        except (TypeError, ValueError):
            continue
        if ahead_by <= 0:
            continue
        _create_draft_pr(name)
        opened.append(name)
    return tuple(opened)


def reconcile_open_pull_requests(
    prs: Sequence[PullRequestRecord],
) -> ReconciliationResult:
    readied: list[int] = []
    merged: list[int] = []
    skipped: list[str] = []

    for pr in prs:
        if pr.head_repo != _repository():
            skipped.append(f"PR #{pr.number}: fork-owned head")
            continue

        checks_ok, checks_message = _checks_green(pr.number)

        if should_ready_and_merge_draft(pr, checks_green=checks_ok):
            code, output = _run(["gh", "pr", "ready", str(pr.number)], timeout=30.0)
            if code != 0:
                skipped.append(
                    f"PR #{pr.number}: could not convert draft to ready: {output[-500:]}"
                )
                continue
            readied.append(pr.number)
            code, output = _run(
                [
                    "gh",
                    "pr",
                    "merge",
                    str(pr.number),
                    "--squash",
                    "--auto",
                    "--delete-branch",
                ],
                timeout=45.0,
            )
            if code == 0:
                merged.append(pr.number)
            else:
                skipped.append(
                    f"PR #{pr.number}: ready but auto-merge not accepted: {output[-500:]}"
                )
            continue

        if is_standard_auto_merge_candidate(pr, checks_green=checks_ok):
            code, output = _run(
                [
                    "gh",
                    "pr",
                    "merge",
                    str(pr.number),
                    "--squash",
                    "--auto",
                    "--delete-branch",
                ],
                timeout=45.0,
            )
            if code == 0:
                merged.append(pr.number)
            else:
                skipped.append(
                    f"PR #{pr.number}: standard-risk checks passed but merge not accepted: {output[-500:]}"
                )
            continue

        skipped.append(
            f"PR #{pr.number}: no automatic action (risk={pr.risk}, draft={pr.is_draft}, "
            f"mergeable={pr.mergeable}, merge_state={pr.merge_state}, checks={checks_message})"
        )

    return ReconciliationResult(
        readied_drafts=tuple(readied),
        auto_merge_requested=tuple(merged),
        skipped=tuple(skipped),
    )


def reconcile(*, json_output: bool = False) -> ReconciliationResult:
    if not gh_available() or not gh_authenticated():
        raise BranchPrReconciliationError(
            "GitHub CLI is required and must be authenticated for branch reconciliation"
        )

    branches = list_branches_ahead_of_main()
    prs = list_open_pull_requests()
    open_heads = frozenset(
        pr.head_branch for pr in prs if pr.head_repo == _repository()
    )
    opened = open_missing_branch_prs(branches, open_heads)

    # A newly opened draft intentionally waits for its initial CI/event cycle.
    prs = list_open_pull_requests()
    result = reconcile_open_pull_requests(prs)

    result = ReconciliationResult(
        opened_drafts=opened,
        readied_drafts=result.readied_drafts,
        auto_merge_requested=result.auto_merge_requested,
        skipped=result.skipped,
    )
    payload = {
        "opened_drafts": list(result.opened_drafts),
        "readied_drafts": list(result.readied_drafts),
        "auto_merge_requested": list(result.auto_merge_requested),
        "skipped": list(result.skipped),
    }
    if json_output:
        print(json.dumps(payload, indent=2))
    else:
        print(
            "PASI branch/PR reconciliation: "
            f"opened={len(result.opened_drafts)} "
            f"readied={len(result.readied_drafts)} "
            f"auto_merge_requested={len(result.auto_merge_requested)}"
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reconcile orphan work branches and open pull requests."
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
