from __future__ import annotations

import argparse
import math
import re
import sys
import time
from datetime import timedelta
from pathlib import Path
from typing import Any, Callable

from scripts import pasi_automation_entrypoint as automation
from scripts import pasi_overnight_engine as legacy
from scripts import pasi_overnight_engine_v2 as supervisor
from scripts import pasi_overnight_hardening as hardening

REPAIR_TIMEOUT_SECONDS = 600.0
MAX_REPAIR_ATTEMPTS = 2
RESPONSE_ARCHIVE_MAX_CHARS = 60_000
PRIMARY_RECOVERY_WINDOW_SECONDS = 3 * 60 * 60
PRIMARY_RECOVERY_POLL_SECONDS = 60.0
MAX_RUNNER_RESTARTS = 8
RUNNER_RESTART_BACKOFF_SECONDS = 30.0
_DIFF_LINE_RE = re.compile(r"^diff --git .+$", re.MULTILINE)


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
    if not patch:
        recovered = _extract_diff_block(response)
        if recovered:
            patch = legacy.normalize_patch(recovered)
    return status, summary, next_task, patch, allow_delete, dict(values)


def _contract_valid(parsed: tuple[str, str, str, str, bool, dict[str, str]]) -> bool:
    status, _summary, next_task, patch, _allow_delete, values = parsed
    contract_ok = legacy.completion_contract_is_satisfied(status, values)
    if patch:
        return contract_ok
    return contract_ok and values.get("repository_progress", "").lower() == "stopped" and bool(next_task.strip())


def _archive_response(
    worktree: Path,
    task_number: int,
    attempt: int,
    response: str,
    *,
    label: str,
) -> None:
    if not response:
        return
    root = worktree / ".runtime" / "overnight" / "responses"
    try:
        root.mkdir(parents=True, exist_ok=True)
        payload = response[-RESPONSE_ARCHIVE_MAX_CHARS:]
        safe_label = re.sub(r"[^a-zA-Z0-9_-]+", "_", label).strip("_") or "response"
        target = root / f"task-{task_number:04d}-attempt-{attempt:02d}-{safe_label}.txt"
        target.write_text(payload + "\n", encoding="utf-8")
    except OSError:
        pass


def _contract_instruction() -> str:
    return """
WEEKLONG RESPONSE CONTRACT:
Return the PASI completion markers exactly as requested. When repository_progress is changed, the patch markers must contain one real unified git diff. When repository_progress is stopped, an empty patch is allowed only when the task is already satisfied and the repository is clean; never invent a cosmetic patch merely to satisfy the format. Never claim tests or evidence that were not actually produced.
"""


def _repair_prompt(task: str, response: str, failure: str, state: Any | None = None) -> str:
    evidence = response[-8_000:] if response else "[no response captured]"
    prior = failure[-4_000:] if failure else "[no previous failure evidence]"
    repair_state = state or supervisor.OvernightState(
        schema_version=2,
        run_id="repair",
        started_at="",
        deadline_at="9999-12-31T23:59:59+00:00",
        worktree="",
        branch="",
        phase="engineering_os",
        current_task=task,
    )
    continuation_builder = getattr(supervisor, "continuation_directive")
    continuation = continuation_builder(repair_state, task)
    return f"""PASI RESPONSE REPAIR REQUEST

The engineering task itself is still active. Do not restart it or abandon the work.

TASK:
{task}

The previous response did not satisfy PASI's machine-readable completion contract. Continue from the existing conversation/repository state and produce the final result now.

{continuation}

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
PASI_RESULT_PATCH_BEGIN
<one unified git diff, plain text only; do not use Markdown fences>
PASI_RESULT_PATCH_END

PREVIOUS RESPONSE EXCERPT:
{evidence}

PREVIOUS FAILURE EVIDENCE:
{prior}

Do not claim tests, edits, or evidence that you did not actually perform. Keep all existing PASI safety and authorization boundaries intact.
"""


def _invoke_repair(task: str, state: Any, response: str, failure: str) -> tuple[int, str]:
    prompt = _repair_prompt(task, response, failure, state)
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


def _invoke_provider_fallback(task: str, state: Any) -> tuple[int, str]:
    return supervisor.command(
        [
            sys.executable,
            "scripts/pasi_provider_router.py",
            "--task",
            _repair_prompt(task, "", "primary ChatGPT provider is unavailable or restricted"),
            "--repo",
            str(state.worktree),
            "--timeout",
            "180",
        ],
        Path(state.worktree),
        timeout=225.0,
    )


def _recover_primary_provider(
    task: str,
    state: Any,
    response: str,
    failure: str,
    primary_invoke: Callable[..., tuple[int, str]],
    ledger: Any,
) -> tuple[int, str]:
    deadline = min(
        supervisor.datetime.fromisoformat(state.deadline_at),
        supervisor.now_utc() + timedelta(seconds=PRIMARY_RECOVERY_WINDOW_SECONDS),
    )
    last_code, last_response = 90, response
    while not supervisor.STOP and supervisor.now_utc() < deadline:
        remaining = (deadline - supervisor.now_utc()).total_seconds()
        supervisor.log_event(
            "primary_provider_recovery_wait",
            task_number=state.task_number,
            attempt=state.current_attempt,
            remaining_seconds=int(max(0, remaining)),
            previous_failure=(failure or response)[-2000:],
        )
        end = supervisor.now_utc() + timedelta(seconds=min(PRIMARY_RECOVERY_POLL_SECONDS, max(1.0, remaining)))
        while not supervisor.STOP and supervisor.now_utc() < min(deadline, end):
            time.sleep(1.0)
        if supervisor.STOP:
            break
        retry_code, retry_response = primary_invoke(task, state, failure, ledger=ledger)
        last_code, last_response = retry_code, retry_response
        if retry_code == 0:
            return retry_code, retry_response
        condition = supervisor.provider_condition(retry_code, retry_response)
        if condition not in {"provider_usage_limit", "auth_required"}:
            break
        response = retry_response or response
        failure = retry_response[-8_000:] or failure
    return last_code, last_response


def _should_not_restart(exit_code: int, state: Any | None, deadline: Any) -> bool:
    if exit_code in {130, 143}:
        return True
    if supervisor.now_utc() >= deadline:
        return True
    if state is None:
        return False
    return state.stop_reason in {"stopped", "keyboard_interrupt", "deadline_reached"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run PASI unattended with resilient response recovery and bounded process restart for weeklong operation.")
    parser.add_argument("--hours", type=float, required=True)
    args, passthrough = parser.parse_known_args()
    if not math.isfinite(args.hours) or args.hours < legacy.MIN_HOURS:
        parser.error(f"--hours must be a finite value >= {legacy.MIN_HOURS:g}")

    supervisor.MAX_HOURS = float("inf")
    legacy.MAX_HOURS = float("inf")

    original_parse = supervisor.parse_response
    original_invoke = hardening.resilient_invoke_chat
    original_verify = supervisor.verify_and_commit
    original_sleep = hardening.nonblocking_sleep

    def parse_response(response: str):
        return _parsed_response(response, original_parse)

    def resilient_invoke_chat(task: str, state: Any, failure: str, *, ledger: Any):
        enriched_task = task.rstrip() + "\n" + _contract_instruction()
        code, response = original_invoke(enriched_task, state, failure, ledger=ledger)
        _archive_response(Path(state.worktree), state.task_number, state.current_attempt, response, label="primary")

        condition = supervisor.provider_condition(code, response)
        if condition in {"provider_usage_limit", "auth_required"}:
            fallback_code, fallback_response = _invoke_provider_fallback(task, state)
            _archive_response(Path(state.worktree), state.task_number, state.current_attempt, fallback_response, label="provider-fallback")
            fallback_parsed = _parsed_response(fallback_response, original_parse)
            if fallback_code == 0 and _contract_valid(fallback_parsed):
                supervisor.log_event(
                    "response_contract_recovered_by_fallback_provider",
                    task_number=state.task_number,
                    attempt=state.current_attempt,
                    condition=condition,
                )
                return 0, fallback_response
            return _recover_primary_provider(
                enriched_task,
                state,
                response,
                fallback_response or response,
                original_invoke,
                ledger,
            )

        parsed = _parsed_response(response, original_parse)
        if code == 0 and _contract_valid(parsed):
            return code, response

        repair_failure = failure or parsed[1] or "response did not satisfy the PASI completion contract"
        for repair_attempt in range(1, MAX_REPAIR_ATTEMPTS + 1):
            repair_code, repair_response = _invoke_repair(enriched_task, state, response, repair_failure)
            _archive_response(
                Path(state.worktree),
                state.task_number,
                state.current_attempt * 10 + repair_attempt,
                repair_response,
                label=f"repair-{repair_attempt}",
            )
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

        fallback = _invoke_provider_fallback(task, state)
        fallback_response = fallback[1]
        _archive_response(Path(state.worktree), state.task_number, state.current_attempt, fallback_response, label="post-repair-fallback")
        fallback_parsed = _parsed_response(fallback_response, original_parse)
        if fallback[0] == 0 and _contract_valid(fallback_parsed):
            supervisor.log_event(
                "response_contract_recovered_by_fallback_provider",
                task_number=state.task_number,
                attempt=state.current_attempt,
                phase="post_repair",
            )
            return 0, fallback_response
        return code, response

    def verify_and_commit(worktree: Path, branch: str, task: str, patch: str, allow_delete: bool, *, push: bool):
        return original_verify(worktree, branch, task, patch, allow_delete, push=push)

    def paced_sleep(state: Any, seconds: float, *, ledger: Any) -> bool:
        wait_seconds = min(max(seconds, 1.0), 900.0)
        if ledger is not None:
            ledger.record(
                "retry_backoff",
                f"Waiting {wait_seconds:.0f} seconds before retrying an unavailable provider/runtime.",
                "Retry automatically after the bounded wait; no security or approval boundary is bypassed.",
                details={"requested_seconds": seconds},
                status="pending",
            )
        deadline = supervisor.datetime.fromisoformat(state.deadline_at)
        end = min(deadline, supervisor.now_utc() + timedelta(seconds=wait_seconds))
        while not supervisor.STOP and supervisor.now_utc() < end:
            time.sleep(min(1.0, max(0.1, (end - supervisor.now_utc()).total_seconds())))
        return not supervisor.STOP and supervisor.now_utc() < deadline

    hardening.resilient_invoke_chat = resilient_invoke_chat
    hardening.nonblocking_sleep = paced_sleep
    supervisor.parse_response = parse_response
    supervisor.verify_and_commit = verify_and_commit

    restart_count = 0
    resume_passthrough = list(passthrough)
    process_deadline = supervisor.now_utc() + timedelta(hours=args.hours)
    try:
        while True:
            supervisor.STOP = False
            sys.argv = ["pasi_automation_entrypoint.py", "--hours", str(args.hours), *resume_passthrough]
            exit_code = automation.main()
            state = supervisor.load_state()
            deadline = supervisor.datetime.fromisoformat(state.deadline_at) if state is not None else process_deadline
            if _should_not_restart(exit_code, state, deadline):
                return exit_code
            if supervisor.now_utc() >= deadline:
                return exit_code
            if restart_count >= MAX_RUNNER_RESTARTS:
                supervisor.log_event(
                    "runner_restart_budget_exhausted",
                    restarts=restart_count,
                    task_number=state.task_number if state is not None else None,
                )
                return exit_code or 1
            restart_count += 1
            if "--resume" not in resume_passthrough:
                resume_passthrough.append("--resume")
            supervisor.log_event(
                "runner_restarting",
                restart_count=restart_count,
                exit_code=exit_code,
                reason=state.stop_reason if state is not None else "no persisted state",
                task_number=state.task_number if state is not None else None,
            )
            supervisor.STOP = False
            end = min(deadline, supervisor.now_utc() + timedelta(seconds=RUNNER_RESTART_BACKOFF_SECONDS))
            while not supervisor.STOP and supervisor.now_utc() < end:
                time.sleep(1.0)
    finally:
        supervisor.parse_response = original_parse
        supervisor.verify_and_commit = original_verify
        hardening.resilient_invoke_chat = original_invoke
        hardening.nonblocking_sleep = original_sleep


if __name__ == "__main__":
    raise SystemExit(main())
