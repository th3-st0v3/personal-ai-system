from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from dataclasses import dataclass


TARGETS = (2, 16, 128, 1024)


@dataclass(frozen=True)
class PullSharkStatus:
    repository: str
    author: str
    merged_prs_observed: int
    next_target: int | None
    remaining_to_next_target: int
    tier_reached: str


def _run(command: list[str], timeout: float = 20.0) -> tuple[int, str]:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)
    return result.returncode, (result.stdout or result.stderr or "").strip()


def _login() -> str:
    code, output = _run(["gh", "api", "user", "--jq", ".login"])
    if code != 0 or not output:
        raise RuntimeError(f"could not determine authenticated GitHub login: {output}")
    return output.splitlines()[-1].strip()


def _merged_count(repository: str, author: str) -> int:
    query = f"repo:{repository} is:pr is:merged author:{author}"
    code, output = _run(["gh", "api", "search/issues", "-f", f"q={query}", "--jq", ".total_count"])
    if code != 0:
        raise RuntimeError(f"could not query merged pull requests: {output}")
    try:
        return int(output.splitlines()[-1].strip())
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"GitHub returned an invalid merged PR count: {output}") from exc


def calculate_status(repository: str, author: str, merged_prs_observed: int) -> PullSharkStatus:
    reached = [target for target in TARGETS if merged_prs_observed >= target]
    next_target = next((target for target in TARGETS if merged_prs_observed < target), None)
    tier_reached = f"{max(reached)} merged PRs" if reached else "below 2 merged PRs"
    remaining = 0 if next_target is None else next_target - merged_prs_observed
    return PullSharkStatus(repository, author, merged_prs_observed, next_target, remaining, tier_reached)


def collect_status(repository: str, author: str | None = None) -> PullSharkStatus:
    if shutil.which("gh") is None:
        raise RuntimeError("GitHub CLI is not installed")
    resolved_author = author or _login()
    return calculate_status(repository, resolved_author, _merged_count(repository, resolved_author))


def main() -> int:
    parser = argparse.ArgumentParser(description="Report account-authored merged PR progress for one PASI repository.")
    parser.add_argument("--repo", default="th3-st0v3/personal-ai-system", help="GitHub repository in owner/name form.")
    parser.add_argument("--author", default="", help="GitHub login; defaults to the authenticated gh account.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        status = collect_status(args.repo, args.author or None)
    except RuntimeError as exc:
        print(f"Pull Shark status unavailable: {exc}")
        return 1

    payload = {
        "repository": status.repository,
        "author": status.author,
        "merged_prs_observed": status.merged_prs_observed,
        "next_target": status.next_target,
        "remaining_to_next_target": status.remaining_to_next_target,
        "tier_reached_observed": status.tier_reached,
        "targets": list(TARGETS),
        "scope_note": "This reports account-authored merged PRs observed in the selected repository; GitHub achievement attribution may include additional platform-level eligibility rules.",
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"Pull Shark: {status.merged_prs_observed} merged PRs observed in {status.repository}")
        if status.next_target is None:
            print("Next configured target: none (1,024 target reached)")
        else:
            print(f"Next configured target: {status.next_target} ({status.remaining_to_next_target} more)")
        print("Configured targets: 2, 16, 128, 1,024")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
