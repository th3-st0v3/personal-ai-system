from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
MAIN_BRANCH = "main"
MAX_TITLE_CHARS = 65
MAX_BODY_CHARS = 8_000
HIGH_RISK_PATH_PREFIXES = (
    ".github/workflows/",
    ".github/pull_request_template.md",
    "automation/chromium/",
    "automation/legacy/tampermonkey/",
    "automation/computer_use/capability_gateway.py",
    "automation/computer_use/local_access.py",
    "automation/computer_use/preapproval.py",
    "automation/computer_use/recovery.py",
    "automation/computer_use/research.py",
    "automation/legacy/",
    "docs/architecture/verified-live-self-update.md",
    "docs/operations/pr-scope-policy.md",
    "docs/operations/runtime-acceptance-gates.md",
    "docs/operations/weeklong-automation.md",
    "SECURITY.md",
    "scripts/check_all.sh",
    "scripts/pasi_chat_guard.py",
    "scripts/pasi_provider_router.py",
    "scripts/pasi_timeout_policy.py",
    "scripts/pasi_promote.py",
    "scripts/cleanup_duplicate_branches.py",
    "scripts/start_pasi_168h.sh",
    "scripts/start_pasi_overnight.sh",
    "scripts/stop_pasi_overnight.sh",
    "scripts/status_pasi_overnight.sh",
    "scripts/check_pasi_weekly_run.sh",
    "automation/orchestrator/",
    "scripts/pasi_overnight_engine_v2.py",
    "scripts/pasi_extended_runtime_entrypoint.py",
    "scripts/pasi_setup.py",
    "scripts/pasi_log_router.py",
    "scripts/pasi_overnight_hardening.py",
)
HIGH_RISK_NAME_PATTERNS = (
    re.compile(r"(^|/)(credentials|secrets?)(\.|/|$)", re.IGNORECASE),
    re.compile(r"(^|/)(id_rsa|id_ed25519|authorized_keys)$", re.IGNORECASE),
)


class PromotionError(RuntimeError):
    pass


@dataclass(frozen=True)
class PromotionResult:
    branch: str
    pr_number: int | None
    pr_url: str
    risk: str
    auto_merge_requested: bool
    message: str


def _run(command: Sequence[str], *, timeout: float = 30.0) -> tuple[int, str]:
    try:
        result = subprocess.run(
            list(command),
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)
    output = ((result.stdout or "") + (result.stderr or "")).strip()
    return result.returncode, output[-12_000:]


def changed_paths(commit: str) -> tuple[str, ...]:
    code, output = _run(
        ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", "--root", commit],
        timeout=20.0,
    )
    if code != 0:
        raise PromotionError(f"could not inspect changed paths: {output}")
    return tuple(sorted({line.strip().replace("\\", "/") for line in output.splitlines() if line.strip()}))


def classify_risk(paths: Sequence[str]) -> str:
    for path in paths:
        normalized = path.replace("\\", "/").lstrip("/")
        if normalized.startswith(HIGH_RISK_PATH_PREFIXES) or any(
            pattern.search(normalized) for pattern in HIGH_RISK_NAME_PATTERNS
        ):
            return "high"
    return "standard"


def gh_available() -> bool:
    return shutil.which("gh") is not None


def gh_authenticated() -> bool:
    if not gh_available():
        return False
    code, _ = _run(["gh", "auth", "status"], timeout=15.0)
    return code == 0


def _branch_pr(branch: str) -> tuple[int | None, str, str]:
    code, output = _run(
        ["gh", "pr", "view", branch, "--json", "number,url,state"],
        timeout=20.0,
    )
    if code != 0:
        return None, "", ""
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        return None, "", ""
    if not isinstance(payload, dict):
        return None, "", ""
    try:
        number = int(payload["number"])
    except (KeyError, TypeError, ValueError):
        return None, "", ""
    return number, str(payload.get("url", "")), str(payload.get("state", "")).upper()


def _find_open_task_pr(task: str) -> tuple[int | None, str, str, str]:
    code, output = _run(
        [
            "gh",
            "pr",
            "list",
            "--state",
            "open",
            "--base",
            MAIN_BRANCH,
            "--limit",
            "100",
            "--json",
            "number,url,title,body,headRefName,headRefOid",
        ],
        timeout=30.0,
    )
    if code != 0:
        return None, "", "", ""
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        return None, "", "", ""
    if not isinstance(payload, list):
        return None, "", "", ""
    expected = re.sub(r"\s+", " ", task).strip().casefold()
    for item in payload:
        if not isinstance(item, dict):
            continue
        body = re.sub(r"\s+", " ", str(item.get("body", ""))).strip().casefold()
        title = re.sub(r"\s+", " ", str(item.get("title", ""))).strip().casefold()
        if f"task: {expected}" in body or expected == title:
            try:
                return (
                    int(item["number"]),
                    str(item.get("url", "")),
                    str(item.get("headRefName", "")),
                    str(item.get("headRefOid", "")),
                )
            except (KeyError, TypeError, ValueError):
                continue
    return None, "", "", ""


def _fast_forward_pr_branch(
    branch: str,
    commit: str,
    current_head: str,
) -> tuple[bool, str]:
    if not branch or not commit or not current_head:
        return False, "existing PR branch metadata is incomplete"
    if commit == current_head:
        return True, "existing PR branch already points at the verified commit"
    code, _ = _run(
        ["git", "merge-base", "--is-ancestor", current_head, commit],
        timeout=15.0,
    )
    if code != 0:
        return False, "verified commit is not a fast-forward descendant of the existing PR head"
    code, output = _run(
        ["git", "push", "origin", f"{commit}:refs/heads/{branch}"],
        timeout=60.0,
    )
    if code != 0:
        return False, f"could not fast-forward existing PR branch: {output}"
    return True, f"fast-forwarded existing PR branch {branch} to {commit}"


def _create_pr(branch: str, title: str, body: str) -> tuple[int, str]:
    code, output = _run(
        [
            "gh",
            "pr",
            "create",
            "--base",
            MAIN_BRANCH,
            "--head",
            branch,
            "--title",
            title[:MAX_TITLE_CHARS],
            "--body",
            body[:MAX_BODY_CHARS],
        ],
        timeout=45.0,
    )
    if code != 0:
        raise PromotionError(f"GitHub PR creation failed: {output}")
    url = output.splitlines()[-1].strip() if output else ""
    number_match = re.search(r"/pull/(\d+)(?:$|\s)", url)
    number = int(number_match.group(1)) if number_match else 0
    return number, url


def _checks_green(pr_number: int) -> tuple[bool, str]:
    code, output = _run(
        ["gh", "pr", "checks", str(pr_number), "--json", "name,bucket,workflow,event"],
        timeout=30.0,
    )
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        return False, "GitHub checks did not return parseable JSON"
    if not isinstance(payload, list) or not payload:
        return False, "no GitHub checks are currently reported for this PR"
    non_passing = []
    for check in payload:
        if not isinstance(check, dict):
            return False, "GitHub returned a malformed check record"
        if check.get("bucket") != "pass":
            non_passing.append(f"{check.get('name', 'unnamed')}: {check.get('bucket', 'unknown')}")
    if code != 0 or non_passing:
        detail = ", ".join(non_passing[:10]) or f"gh pr checks exited with {code}"
        return False, detail
    return True, f"all {len(payload)} reported GitHub checks passed"


def _enable_auto_merge(pr_number: int) -> tuple[bool, str]:
    code, output = _run(
        ["gh", "pr", "merge", str(pr_number), "--squash", "--auto", "--delete-branch"],
        timeout=45.0,
    )
    return code == 0, output


def promote(commit: str, branch: str, task: str, *, auto_merge_standard: bool = True) -> PromotionResult:
    if branch == MAIN_BRANCH:
        return PromotionResult(branch, None, "", "standard", False, "already on main")
    if not gh_available():
        return PromotionResult(
            branch,
            None,
            "",
            "unknown",
            False,
            "GitHub CLI is not installed; commit remains on the pushed branch",
        )
    if not gh_authenticated():
        return PromotionResult(
            branch,
            None,
            "",
            "unknown",
            False,
            "GitHub CLI is not authenticated; commit remains on the pushed branch",
        )

    paths = changed_paths(commit)
    risk = classify_risk(paths)
    title = (
        re.sub(r"[^A-Za-z0-9 .:_/-]+", "", task).strip()[:MAX_TITLE_CHARS]
        or "PASI verified automation change"
    )
    path_lines = "\n".join(f"- `{path}`" for path in paths[:100])
    body = (
        "## PASI verified automation change\n\n"
        f"Task: {task}\n\n"
        f"Commit: `{commit}`\n\n"
        f"Risk class: **{risk}**\n\n"
        "Deterministic repository verification completed before this PR was created. "
        "The commit was produced from a validated PASI task patch.\n\n"
        "### Changed paths\n"
        f"{path_lines or '- none'}\n\n"
        "PASI never auto-merges high-risk controller, browser, security-boundary, "
        "provider-routing, or workflow changes. Those changes are opened as normal PRs "
        "for human review."
    )

    pr_number, pr_url, pr_state = _branch_pr(branch)
    if pr_number is None:
        (
            existing_number,
            existing_url,
            existing_head_branch,
            existing_head_sha,
        ) = _find_open_task_pr(task)
        if existing_number is not None:
            if existing_head_branch == branch:
                pr_number, pr_url = existing_number, existing_url
            else:
                reused, reuse_message = _fast_forward_pr_branch(
                    existing_head_branch,
                    commit,
                    existing_head_sha,
                )
                if not reused:
                    return PromotionResult(
                        branch,
                        existing_number,
                        existing_url,
                        risk,
                        False,
                        "an open PR for this task already exists on a different branch; "
                        "no duplicate PR was created and its branch was not rewritten: "
                        f"{reuse_message}",
                    )
                pr_number, pr_url = existing_number, existing_url

    if pr_number is None:
        pr_number, pr_url = _create_pr(branch, title, body)
    elif pr_state == "CLOSED":
        return PromotionResult(
            branch,
            pr_number,
            pr_url,
            risk,
            False,
            "an existing PR for this branch is closed; it remains closed and no duplicate PR was created",
        )
    elif pr_state == "MERGED":
        pr_number, pr_url = _create_pr(branch, title, body)
    if not pr_number:
        return PromotionResult(
            branch,
            None,
            pr_url,
            risk,
            False,
            "PR was created but its numeric id could not be parsed",
        )

    if risk == "standard" and auto_merge_standard:
        checks_ok, checks_message = _checks_green(pr_number)
        if not checks_ok:
            return PromotionResult(
                branch,
                pr_number,
                pr_url,
                risk,
                False,
                f"standard-risk PR created; auto-merge withheld until all GitHub checks "
                f"pass: {checks_message[-2_000:]}",
            )
        merged, output = _enable_auto_merge(pr_number)
        if merged:
            return PromotionResult(
                branch,
                pr_number,
                pr_url,
                risk,
                True,
                f"standard-risk PR created after verified checks ({checks_message}); "
                "auto-merge requested",
            )
        return PromotionResult(
            branch,
            pr_number,
            pr_url,
            risk,
            False,
            f"standard-risk PR created; auto-merge request was not accepted: {output[-2_000:]}",
        )

    return PromotionResult(
        branch,
        pr_number,
        pr_url,
        risk,
        False,
        "high-risk PR created for human review",
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Promote a verified PASI automation commit to a GitHub PR, with risk-gated auto-merge."
    )
    parser.add_argument("--commit", required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--no-auto-merge-standard", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        result = promote(
            args.commit,
            args.branch,
            args.task,
            auto_merge_standard=not args.no_auto_merge_standard,
        )
    except PromotionError as exc:
        print(f"promotion failed: {exc}")
        return 1
    payload = {
        "branch": result.branch,
        "pr_number": result.pr_number,
        "pr_url": result.pr_url,
        "risk": result.risk,
        "auto_merge_requested": result.auto_merge_requested,
        "message": result.message,
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"PASI promotion: {result.message}")
        if result.pr_url:
            print(f"PR: {result.pr_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
