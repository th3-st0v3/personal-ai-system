from __future__ import annotations

import argparse
import math
import re
import sys
from pathlib import Path
from typing import Any

from scripts import pasi_overnight_engine as legacy
from scripts import pasi_overnight_engine_v2 as supervisor
from scripts import pasi_overnight_hardening as hardening

REPAIR_TIMEOUT_SECONDS = 600.0
MAX_REPAIR_ATTEMPTS = 2
RESPONSE_ARCHIVE_MAX_CHARS = 60_000
NO_CHANGE_SENTINEL = "__PASI_NO_CHANGE__"
_DIFF_LINE_RE = re.compile(r"^diff --git .+$", re.MULTILINE)
_NO_CHANGE_RE = re.compile(r"^PASI_RESULT_NO_CHANGE:\s*true$", re.MULTILINE | re.IGNORECASE)


def _extract_diff_block(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    matches = list(_DIFF_LINE_RE.finditer(normalized))
    if not matches:
        return ""
    candidate = normalized[matches[-1].start():]
    lines = candidate.splitlines()
    kept: list[str] = []
    for line in lines:
        if line.strip().startswith("```"):
            break
        if line.startswith("PASI_RESULT_") and kept:
            break
        kept.append(line)
    patch = "\n".join(kept).strip() + "\n"
    return patch if patch.strip() else ""


def _parsed_response(response: str, original_parse: Any) -> tuple[str, str, str, str, bool, dict[str, str]]:
    status, summary, next_task, patch, allow_delete, values = original_parse(response)
    values = dict(values)
    if _NO_CHANGE_RE.search(response):
        values["no_change"] = "true"
        if status == "complete" and not patch:
            return status, summary or "Task completed without a repository change; no safe change was necessary.", next_task, NO_CHANGE_SENTINEL, allow_delete, values
    if not patch:
        recovered = _extract_diff_block(response)
        if recovered:
            patch = legacy.normalize_patch(recovered)
    return status, summary, next_task, patch, allow_delete, values


def _contract_valid(parsed: tuple[str, str, str, str, bool, dict[str, str]]) -> bool:
    status, _summary, _next_task, patch, _allow_delete, values = parsed
    if values.get("no_change") == "true" and patch == NO_CHANGE_SENTINEL:
        return legacy.completion_contract_is_satisfied(status, values)
    return legacy.completion_contract_is_satisfied(status, values) and bool(patch)


def _archive_response(worktree: Path, task_number: int, attempt: int, response: str) -> None:
    if not response:
        return
    root = worktree / ".runtime" / "overnight" / "responses"
    try:
        root.mkdir(parents=True, exist_ok=True)
        payload = response[-RESPONSE_ARCHIVE_MAX_CHARS:]
        target = root / f"task-{task_number:04d}-attempt-{attempt:02d}.txt"
        target.write_text(payload + "\n", encoding="utf-8")
    except OSError:
        pass


def _repair_prompt(task: str, response: str, failure: str) -> str:
    evidence = response[-8_000:] if response else "[no response captured]"
    prior = failure[-4_000:] if failure else "[no previous failure evidence]"
    return f"""PASI RESPONSE REPAIR REQUEST

The engineering task itself is still active. Do not restart it or abandon the work.

TASK:
{task}

The previous response did not satisfy PASI's machine-readable completion contract. Continue from the existing conversation/repository state and produce the final result now.

REQUIRED OUTPUT:
PASI_RESULT_STATUS: complete|needs_revision|blocked
PASI_RESULT_SUMMARY: one concise sentence
PASI_RESULT_NEXT_TASK: one concrete high-value next task
PASI_RESULT_REQUIREMENTS: complete
PASI_RESULT_LIMITATIONS: handled|none|not_applicable
PASI_RESULT_RESEARCH: performed|not_applicable
PASI_RESULT_UX: verified|not_applicable
PASI_RESULT_BACKEND: verified|not_applicable
PASI_RESULT_EVIDENCE: concise reproducible tests/verification evidence
PASI_RESULT_ALLOW_DELETE: true|false
PASI_RESULT_NO_CHANGE: true|false
PASI_RESULT_PATCH_BEGIN
<one unified git diff, plain text only; do not use Markdown fences>
PASI_RESULT_PATCH_END

Use PASI_RESULT_NO_CHANGE: true only when there is genuinely no safe, necessary repository change. In that case, keep the patch markers empty and provide concrete evidence explaining why no change is required.

PREVIOUS RESPONSE EXCERPT:
{evidence}

PREVIOUS FAILURE EVIDENCE:
{prior}

Do not claim tests, edits, or evidence that you did not actually perform. Keep all existing PASI safety and authorization boundaries intact.
"""


def _invoke_repair(task: str, state: Any, response: str, failure: str) -> tuple[int, str]:
    prompt = _repair_prompt(task, response, failure)
    return supervisor.command(
        [
            sys.executable,
            "scripts/pasi_chat_guard.py",
            prompt,
            "--github",
            "auto",
            "--timeout",
            str(REPAIR_TIMEOUT_SECONDS),
        ],
        Path(state.worktree),
        timeout=REPAIR_TIMEOUT_SECONDS + 45.0,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run PASI unattended with resilient response recovery for weeklong operation.")
    parser.add_argument("--hours", type=float, required=True)
    args, passthrough = parser.parse_known_args()
    if not math.isfinite(args.hours) or args.hours < legacy.MIN_HOURS:
        parser.error(f"--hours must be a finite value >= {legacy.MIN_HOURS:g}")

    supervisor.MAX_HOURS = float("inf")
    legacy.MAX_HOURS = float("inf")

    original_parse = supervisor.parse_response
    original_invoke = hardening.resilient_invoke_chat
    original_verify = supervisor.verify_and_commit

    def parse_response(response: str):
        return _parsed_response(response, original_parse)

    def resilient_invoke_chat(task: str, state: Any, failure: str, *, ledger: Any):
        code, response = original_invoke(task, state, failure, ledger=ledger)
        _archive_response(Path(state.worktree), state.task_number, state.current_attempt, response)
        parsed = _parsed_response(response, original_parse)
        if code == 0 and _contract_valid(parsed):
            return code, response

        repair_failure = failure or parsed[1] or "response did not satisfy the PASI completion contract"
        for repair_attempt in range(1, MAX_REPAIR_ATTEMPTS + 1):
            repair_code, repair_response = _invoke_repair(task, state, response, repair_failure)
            _archive_response(Path(state.worktree), state.task_number, state.current_attempt * 10 + repair_attempt, repair_response)
            if repair_response:
                response = repair_response
            parsed = _parsed_response(response, original_parse)
            if repair_code == 0 and _contract_valid(parsed):
                supervisor.log_event(
                    "response_contract_repaired",
                    task_number=state.task_number,
                    attempt=state.current_attempt,
                    repair_attempt=repair_attempt,
                )
                return 0, response
            repair_failure = parsed[1] or response[-8_000:] or repair_failure

        fallback = supervisor.command(
            [
                sys.executable,
                "scripts/pasi_provider_router.py",
                "--task",
                _repair_prompt(task, response, repair_failure),
                "--repo",
                str(state.worktree),
                "--timeout",
                "180",
            ],
            Path(state.worktree),
            timeout=225.0,
        )
        fallback_response = fallback[1]
        _archive_response(Path(state.worktree), state.task_number, state.current_attempt, fallback_response)
        fallback_parsed = _parsed_response(fallback_response, original_parse)
        if fallback[0] == 0 and _contract_valid(fallback_parsed):
            supervisor.log_event(
                "response_contract_recovered_by_fallback_provider",
                task_number=state.task_number,
                attempt=state.current_attempt,
            )
            return 0, fallback_response
        return code, response

    def verify_and_commit(worktree: Path, branch: str, task: str, patch: str, allow_delete: bool, *, push: bool):
        if patch == NO_CHANGE_SENTINEL:
            return "NO_CHANGE", "PASI_RESULT_NO_CHANGE was explicitly verified; no repository change was necessary."
        return original_verify(worktree, branch, task, patch, allow_delete, push=push)

    supervisor.parse_response = parse_response
    supervisor.verify_and_commit = verify_and_commit
    hardening.resilient_invoke_chat = resilient_invoke_chat
    try:
        sys.argv = ["pasi_overnight_hardening.py", "--hours", str(args.hours), *passthrough]
        return hardening.main()
    finally:
        supervisor.parse_response = original_parse
        supervisor.verify_and_commit = original_verify
        hardening.resilient_invoke_chat = original_invoke


if __name__ == "__main__":
    raise SystemExit(main())
