from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = REPOSITORY_ROOT / ".runtime" / "overnight"
STATE_PATH = RUNTIME_DIR / "state.json"
LOG_PATH = RUNTIME_DIR / "events.jsonl"
DEFAULT_WORKTREE = Path.home() / ".pasi-worktrees" / "personal-ai-system-overnight"
DEFAULT_DURATION_HOURS = 10.0
MIN_DURATION_HOURS = 8.0
MAX_DURATION_HOURS = 12.0
CONTROLLER_SERVER_URL = "http://127.0.0.1:8766/health"
BRIDGE_HEALTH_URL = "http://127.0.0.1:8765/health"
MAX_PATCH_BYTES = 250_000
MAX_COMMAND_OUTPUT_CHARS = 20_000

FORBIDDEN_PATH_PARTS = {
    ".git",
    ".env",
    ".env.local",
    ".env.production",
}
FORBIDDEN_PATH_PATTERNS = (
    re.compile(r"(^|/)(id_rsa|id_ed25519|authorized_keys)$", re.IGNORECASE),
    re.compile(r"(^|/)(credentials|secrets?)(\.|/|$)", re.IGNORECASE),
)
DIFF_PATH_RE = re.compile(r"^diff --git a/(.+) b/(.+)$", re.MULTILINE)
PATCH_BEGIN = "PASI_RESULT_PATCH_BEGIN"
PATCH_END = "PASI_RESULT_PATCH_END"
TASK_RE = re.compile(r"^PASI_RESULT_NEXT_TASK:\s*(.+)$", re.MULTILINE)
STATUS_RE = re.compile(r"^PASI_RESULT_STATUS:\s*(.+)$", re.MULTILINE)
SUMMARY_RE = re.compile(r"^PASI_RESULT_SUMMARY:\s*(.+)$", re.MULTILINE)

BACKLOG = [
    "Audit the ChatGPT computer-use control path end to end and remove avoidable polling, duplicated state, and brittle browser assumptions while preserving all current tests and safety boundaries.",
    "Harden the PASI task continuation loop so completed work deterministically produces the next highest-value task from verified repository gaps, with bounded retries and persistent recovery state.",
    "Improve the ChatGPT controller's browser compatibility and response extraction using current DOM evidence patterns, while keeping provider-specific selectors isolated to the controller.",
    "Improve the engineering evidence and verification pipeline so task completion is based on reproducible tests, diagnostics, and repository state instead of model claims.",
    "Improve the PASI UX/UI for monitoring automation state, task progress, failures, verification evidence, and safe human intervention; ensure backend and frontend behavior remain aligned.",
]

STOP_REQUESTED = False


@dataclass
class RunnerState:
    run_id: str
    started_at: str
    deadline_at: str
    worktree: str
    branch: str
    current_task: str
    task_number: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    last_result: str = ""
    next_task: str = ""

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.isoformat()


def log_event(kind: str, **data: Any) -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"timestamp": iso(utc_now()), "kind": kind, **data}
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def save_state(state: RunnerState) -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_state() -> RunnerState | None:
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    required = {"run_id", "started_at", "deadline_at", "worktree", "branch", "current_task"}
    if not required.issubset(data):
        return None
    return RunnerState(
        run_id=str(data["run_id"]),
        started_at=str(data["started_at"]),
        deadline_at=str(data["deadline_at"]),
        worktree=str(data["worktree"]),
        branch=str(data["branch"]),
        current_task=str(data["current_task"]),
        task_number=int(data.get("task_number", 0)),
        completed_tasks=int(data.get("completed_tasks", 0)),
        failed_tasks=int(data.get("failed_tasks", 0)),
        last_result=str(data.get("last_result", "")),
        next_task=str(data.get("next_task", "")),
    )


def run_command(command: list[str], cwd: Path, *, timeout: float = 300.0) -> tuple[int, str]:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)
    output = ((result.stdout or "") + (result.stderr or "")).strip()
    return result.returncode, output[-MAX_COMMAND_OUTPUT_CHARS:]


def health(url: str, *, timeout: float = 3.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return 200 <= response.status < 300
    except (OSError, urllib.error.URLError):
        return False


def ensure_local_services() -> list[subprocess.Popen[str]]:
    children: list[subprocess.Popen[str]] = []
    if not health(BRIDGE_HEALTH_URL):
        log_event("service_start", service="bridge")
        children.append(
            subprocess.Popen(
                [sys.executable, "-m", "automation.orchestrator.bridge"],
                cwd=REPOSITORY_ROOT,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
            )
        )
    if not health(CONTROLLER_SERVER_URL):
        log_event("service_start", service="controller_distribution")
        children.append(
            subprocess.Popen(
                [sys.executable, "scripts/pasi_controller_server.py"],
                cwd=REPOSITORY_ROOT,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
            )
        )
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        if health(BRIDGE_HEALTH_URL) and health(CONTROLLER_SERVER_URL):
            return children
        time.sleep(0.5)
    raise RuntimeError(
        "PASI local services are not healthy. Start automation.orchestrator.bridge and scripts/pasi_controller_server.py and retry."
    )


def ensure_worktree(worktree: Path, branch: str) -> None:
    worktree.parent.mkdir(parents=True, exist_ok=True)
    if not (worktree / ".git").exists():
        code, output = run_command(
            ["git", "worktree", "add", "-B", branch, str(worktree), "main"],
            REPOSITORY_ROOT,
            timeout=60,
        )
        if code != 0:
            raise RuntimeError(f"could not create overnight worktree: {output}")
    else:
        code, output = run_command(["git", "checkout", branch], worktree, timeout=30)
        if code != 0:
            raise RuntimeError(f"could not select overnight branch: {output}")
    code, output = run_command(["git", "status", "--porcelain"], worktree, timeout=15)
    if code != 0:
        raise RuntimeError(f"could not inspect overnight worktree: {output}")
    if output:
        raise RuntimeError("overnight worktree must start clean; refusing to overwrite existing local changes")


def validate_patch_paths(patch: str, allow_delete: bool) -> None:
    if len(patch.encode("utf-8")) > MAX_PATCH_BYTES:
        raise ValueError("model patch exceeds configured size bound")
    matches = DIFF_PATH_RE.findall(patch)
    if not matches:
        raise ValueError("model response did not contain a unified git patch")
    for old_path, new_path in matches:
        for raw_path in (old_path, new_path):
            path = raw_path.replace("\\", "/")
            parts = Path(path).parts
            if path.startswith("/") or ".." in parts:
                raise ValueError(f"unsafe patch path: {raw_path}")
            if any(part in FORBIDDEN_PATH_PARTS for part in parts):
                raise ValueError(f"forbidden patch path: {raw_path}")
            if any(pattern.search(path) for pattern in FORBIDDEN_PATH_PATTERNS):
                raise ValueError(f"forbidden credential/secret path: {raw_path}")
        if not allow_delete and (old_path == "/dev/null" or new_path == "/dev/null"):
            raise ValueError("file deletion requires PASI_RESULT_ALLOW_DELETE: true")


def extract_response(response: str) -> tuple[str, str, str, str, bool]:
    status_match = STATUS_RE.search(response)
    summary_match = SUMMARY_RE.search(response)
    task_match = TASK_RE.search(response)
    status = status_match.group(1).strip().lower() if status_match else "blocked"
    summary = summary_match.group(1).strip() if summary_match else ""
    next_task = task_match.group(1).strip() if task_match else ""
    allow_delete = bool(re.search(r"^PASI_RESULT_ALLOW_DELETE:\s*true$", response, re.MULTILINE | re.IGNORECASE))
    if PATCH_BEGIN in response and PATCH_END in response:
        patch = response.split(PATCH_BEGIN, 1)[1].split(PATCH_END, 1)[0].strip()
    else:
        patch = ""
    return status, summary, next_task, patch, allow_delete


def build_task_prompt(task: str, state: RunnerState, *, repair_output: str = "") -> str:
    repair = ""
    if repair_output:
        repair = f"""

PREVIOUS VALIDATION FAILURE:
{repair_output[-12_000:]}

Treat the failure as evidence. Diagnose it, correct it in the patch, and do not declare completion until the verification path passes.
"""
    return f"""You are the implementation engineer inside an unattended PASI overnight coding run.

CURRENT TASK:
{task}

RUN CONTEXT:
- Run ID: {state.run_id}
- Task number: {state.task_number}
- Work branch: {state.branch}
- The local worktree is the execution authority for changes.
- The GitHub repository is private and is available to you through the connected GitHub app when repository context is needed.

COMPLETION CONTRACT:
A task is complete only when all stated requirements are implemented, relevant limitations have a concrete workaround when one exists, useful additional features have been researched and implemented when appropriate, backend behavior is functioning, UX/UI is functioning and aesthetically coherent for the scope, and verification evidence supports the result.
For UX/UI work, compare against current relevant products/sites when appropriate and use actual working behavior rather than screenshots alone.
Do not claim a file was changed, tests passed, research was performed, or a feature works unless your patch and evidence support it.

OUTPUT CONTRACT:
Return the following machine-readable markers exactly once:
PASI_RESULT_STATUS: complete|needs_revision|blocked
PASI_RESULT_SUMMARY: one concise sentence
PASI_RESULT_NEXT_TASK: one concrete high-value next task; omit only when there is genuinely no useful next task
PASI_RESULT_ALLOW_DELETE: true   (only when the patch legitimately needs file deletion)
PASI_RESULT_PATCH_BEGIN
<one unified git diff that implements the task>
PASI_RESULT_PATCH_END

The patch must be self-contained, safe to apply with `git apply`, and limited to this repository. Do not emit shell commands as the mechanism for making changes.
{repair}
"""


def select_next_task(state: RunnerState, recent_summary: str) -> str:
    prompt = f"""Select the next concrete implementation task for PASI after the prior task below.

Prior task result:
{recent_summary}

The repository is an evolving personal AI system. Choose one measurable task that improves automation, reliability, computer-use capability, verification, research, UX, or maintainability. Do not choose filler. Prefer work that can be implemented and verified in one focused coding cycle.

Return exactly one line beginning with: PASI_NEXT_TASK: """
    temp_task = state.current_task
    code, output = run_command(
        [sys.executable, "scripts/pasi_chat.py", prompt, "--github", "always", "--timeout", "600"],
        Path(state.worktree),
        timeout=660,
    )
    if code == 0:
        match = re.search(r"PASI_NEXT_TASK:\s*(.+)", output)
        if match:
            candidate = match.group(1).strip()
            if candidate:
                return candidate
    # Deterministic fallback keeps the worker productive without trusting a model to invent filler.
    index = state.completed_tasks % len(BACKLOG)
    return BACKLOG[index]


def apply_patch_and_verify(worktree: Path, patch: str, allow_delete: bool) -> tuple[bool, str]:
    validate_patch_paths(patch, allow_delete)
    check_code, check_output = run_command(
        ["git", "apply", "--check", "--whitespace=nowarn"],
        worktree,
        timeout=60,
    )
    if check_code != 0:
        return False, f"git apply --check failed:\n{check_output}"
    apply_code, apply_output = run_command(
        ["git", "apply", "--whitespace=nowarn"],
        worktree,
        timeout=60,
    )
    if apply_code != 0:
        return False, f"git apply failed:\n{apply_output}"

    test_code, test_output = run_command(["bash", "scripts/check_all.sh"], worktree, timeout=900)
    if test_code != 0:
        return False, f"canonical validation failed:\n{test_output}"
    return True, test_output


def git_commit_and_push(worktree: Path, branch: str, task: str, *, push: bool) -> str:
    message = re.sub(r"[^A-Za-z0-9 .:_/-]+", "", task).strip()
    message = (message[:65] or "overnight PASI task")
    code, output = run_command(["git", "add", "-A"], worktree, timeout=30)
    if code != 0:
        raise RuntimeError(f"git add failed: {output}")
    code, output = run_command(["git", "diff", "--cached", "--quiet"], worktree, timeout=30)
    if code == 0:
        raise RuntimeError("task reported completion but produced no committed file changes")
    code, output = run_command(["git", "commit", "-m", f"pasi: {message}"], worktree, timeout=120)
    if code != 0:
        raise RuntimeError(f"git commit failed: {output}")
    commit = run_command(["git", "rev-parse", "HEAD"], worktree, timeout=15)[1]
    if push:
        code, output = run_command(["git", "push", "--set-upstream", "origin", branch], worktree, timeout=180)
        if code != 0:
            raise RuntimeError(f"git push failed: {output}")
    return commit


def reset_after_failed_task(worktree: Path) -> None:
    code, output = run_command(["git", "reset", "--hard", "HEAD"], worktree, timeout=60)
    if code != 0:
        raise RuntimeError(f"failed to reset rejected task patch: {output}")
    code, output = run_command(["git", "clean", "-fd"], worktree, timeout=60)
    if code != 0:
        raise RuntimeError(f"failed to clean rejected task artifacts: {output}")


def request_task_response(task: str, state: RunnerState, *, repair_output: str = "") -> tuple[int, str]:
    prompt = build_task_prompt(task, state, repair_output=repair_output)
    return run_command(
        [sys.executable, "scripts/pasi_chat.py", prompt, "--github", "always", "--timeout", "900"],
        Path(state.worktree),
        timeout=960,
    )


def next_task_for_state(state: RunnerState, next_task: str, summary: str) -> str:
    if next_task.strip():
        return next_task.strip()
    return select_next_task(state, summary)


def handle_signal(signum: int, _frame: object) -> None:
    global STOP_REQUESTED
    STOP_REQUESTED = True
    log_event("stop_requested", signal=signum)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a bounded unattended PASI engineering loop.")
    parser.add_argument("--hours", type=float, default=DEFAULT_DURATION_HOURS)
    parser.add_argument("--task", default="Optimize PASI automation so the most work is achieved with the least repeated human input while preserving safe human approval boundaries and making the computer-use control plane reliable for long unattended operation.")
    parser.add_argument("--worktree", type=Path, default=DEFAULT_WORKTREE)
    parser.add_argument("--branch", default=f"pasi/overnight-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
    parser.add_argument("--no-push", action="store_true")
    args = parser.parse_args()

    if not (MIN_DURATION_HOURS <= args.hours <= MAX_DURATION_HOURS):
        parser.error(f"--hours must be between {MIN_DURATION_HOURS:g} and {MAX_DURATION_HOURS:g}")

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    children: list[subprocess.Popen[str]] = []
    try:
        code, output = run_command(["git", "fetch", "origin", "main"], REPOSITORY_ROOT, timeout=120)
        if code != 0:
            raise RuntimeError(f"git fetch origin main failed: {output}")
        ensure_worktree(args.worktree.expanduser().resolve(), args.branch)
        children = ensure_local_services()

        started = utc_now()
        state = RunnerState(
            run_id=f"overnight-{uuid.uuid4().hex}",
            started_at=iso(started),
            deadline_at=iso(started.timestamp() and started.replace()),
            worktree=str(args.worktree.expanduser().resolve()),
            branch=args.branch,
            current_task=args.task.strip(),
        )
        state.deadline_at = iso(started + __import__("datetime").timedelta(hours=args.hours))
        save_state(state)
        log_event("run_started", **state.to_dict(), push=not args.no_push)

        repair_output = ""
        controller_backoff = 5.0
        while not STOP_REQUESTED and utc_now() < datetime.fromisoformat(state.deadline_at):
            state.task_number += 1
            state.current_task = state.current_task.strip()
            save_state(state)
            log_event("task_started", task_number=state.task_number, task=state.current_task)

            # The ChatGPT browser controller can temporarily disappear while the user refreshes ChatGPT.
            # Retry with bounded backoff rather than spinning or abandoning the overnight run.
            attempt = 0
            while not STOP_REQUESTED:
                attempt += 1
                if utc_now() >= datetime.fromisoformat(state.deadline_at):
                    break
                code, response = request_task_response(state.current_task, state, repair_output=repair_output)
                if code == 0:
                    controller_backoff = 5.0
                    break
                if "browser controller is not reporting a live heartbeat" not in response.lower():
                    raise RuntimeError(f"ChatGPT task invocation failed:\n{response}")
                sleep_for = min(controller_backoff, 60.0)
                log_event("controller_wait", attempt=attempt, sleep_seconds=sleep_for)
                time.sleep(sleep_for)
                controller_backoff = min(controller_backoff * 2.0, 60.0)
            if STOP_REQUESTED:
                break
            if utc_now() >= datetime.fromisoformat(state.deadline_at):
                break

            status, summary, next_task, patch, allow_delete = extract_response(response)
            log_event("task_response", task_number=state.task_number, status=status, summary=summary, patch_bytes=len(patch.encode("utf-8")), next_task=next_task)
            if status not in {"complete", "needs_revision"} or not patch:
                state.failed_tasks += 1
                state.last_result = summary or "model did not return an applicable implementation patch"
                save_state(state)
                repair_output = state.last_result
                reset_after_failed_task(Path(state.worktree))
                state.current_task = f"Recover the blocked PASI task: {state.current_task}. Diagnose why the implementation response was incomplete and implement a verified workaround."
                continue

            worktree = Path(state.worktree)
            ok, verification = apply_patch_and_verify(worktree, patch, allow_delete)
            if not ok:
                log_event("task_verification_failed", task_number=state.task_number, error=verification)
                state.failed_tasks += 1
                state.last_result = verification[-6_000:]
                save_state(state)
                reset_after_failed_task(worktree)
                repair_output = verification
                continue

            if status != "complete":
                log_event("task_requires_revision", task_number=state.task_number, summary=summary)
                reset_after_failed_task(worktree)
                repair_output = summary or verification
                continue

            commit = git_commit_and_push(worktree, state.branch, state.current_task, push=not args.no_push)
            state.completed_tasks += 1
            state.last_result = summary or "validated task completed"
            state.next_task = next_task
            save_state(state)
            log_event("task_completed", task_number=state.task_number, commit=commit, summary=summary, next_task=next_task)

            repair_output = ""
            state.current_task = next_task_for_state(state, next_task, summary)
            save_state(state)

        state.last_result = "stopped by operator" if STOP_REQUESTED else "overnight deadline reached"
        save_state(state)
        log_event("run_finished", completed_tasks=state.completed_tasks, failed_tasks=state.failed_tasks, reason=state.last_result)
        return 0
    except Exception as exc:
        log_event("run_failed", error=str(exc))
        return 1
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()


if __name__ == "__main__":
    raise SystemExit(main())
