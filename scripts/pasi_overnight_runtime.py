from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = REPOSITORY_ROOT / ".runtime" / "overnight"
STATE_PATH = RUNTIME_DIR / "state.json"
LOG_PATH = RUNTIME_DIR / "events.jsonl"
PID_PATH = RUNTIME_DIR / "runner.pid"
DEFAULT_WORKTREE = Path.home() / ".pasi-worktrees" / "personal-ai-system-overnight"
DEFAULT_DURATION_HOURS = 10.0
MIN_DURATION_HOURS = 8.0
MAX_DURATION_HOURS = 12.0
BRIDGE_HEALTH_URL = "http://127.0.0.1:8765/health"
CONTROLLER_SERVER_HEALTH_URL = "http://127.0.0.1:8766/health"
MAX_PATCH_BYTES = 250_000
MAX_COMMAND_OUTPUT_CHARS = 20_000
MAX_TASK_ATTEMPTS = 3
MAX_CONTROLLER_BACKOFF_SECONDS = 60.0

FORBIDDEN_PATH_PARTS = frozenset({".git", ".env", ".env.local", ".env.production"})
FORBIDDEN_PATH_PATTERNS = (
    re.compile(r"(^|/)(id_rsa|id_ed25519|authorized_keys)$", re.IGNORECASE),
    re.compile(r"(^|/)(credentials|secrets?)(\.|/|$)", re.IGNORECASE),
)
DIFF_PATH_RE = re.compile(r"^diff --git a/(.+) b/(.+)$", re.MULTILINE)
PATCH_BEGIN = "PASI_RESULT_PATCH_BEGIN"
PATCH_END = "PASI_RESULT_PATCH_END"
MARKERS = {
    "status": re.compile(r"^PASI_RESULT_STATUS:\s*(.+)$", re.MULTILINE),
    "summary": re.compile(r"^PASI_RESULT_SUMMARY:\s*(.+)$", re.MULTILINE),
    "next_task": re.compile(r"^PASI_RESULT_NEXT_TASK:\s*(.+)$", re.MULTILINE),
    "requirements": re.compile(r"^PASI_RESULT_REQUIREMENTS:\s*(.+)$", re.MULTILINE),
    "limitations": re.compile(r"^PASI_RESULT_LIMITATIONS:\s*(.+)$", re.MULTILINE),
    "research": re.compile(r"^PASI_RESULT_RESEARCH:\s*(.+)$", re.MULTILINE),
    "ux": re.compile(r"^PASI_RESULT_UX:\s*(.+)$", re.MULTILINE),
    "backend": re.compile(r"^PASI_RESULT_BACKEND:\s*(.+)$", re.MULTILINE),
    "evidence": re.compile(r"^PASI_RESULT_EVIDENCE:\s*(.+)$", re.MULTILINE),
}

BACKLOG = (
    "Audit the ChatGPT computer-use control path end to end and remove avoidable polling, duplicated state, and brittle browser assumptions while preserving current tests and safety boundaries.",
    "Harden PASI task continuation so completed work deterministically produces the next highest-value task from verified repository gaps, with bounded retries and persistent recovery state.",
    "Improve the ChatGPT controller browser compatibility and response extraction using current DOM evidence patterns while keeping provider-specific selectors isolated to the controller.",
    "Improve the engineering evidence and verification pipeline so task completion is based on reproducible tests, diagnostics, and repository state instead of model claims.",
    "Improve the PASI UX/UI for monitoring automation state, task progress, failures, verification evidence, and safe human intervention while keeping backend behavior aligned.",
)

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
    current_attempt: int = 0
    last_result: str = ""
    next_task: str = ""
    recent_tasks: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "deadline_at": self.deadline_at,
            "worktree": self.worktree,
            "branch": self.branch,
            "current_task": self.current_task,
            "task_number": self.task_number,
            "completed_tasks": self.completed_tasks,
            "failed_tasks": self.failed_tasks,
            "current_attempt": self.current_attempt,
            "last_result": self.last_result,
            "next_task": self.next_task,
            "recent_tasks": self.recent_tasks[-10:],
        }


class RunnerError(RuntimeError):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def log_event(kind: str, **data: Any) -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"timestamp": utc_now().isoformat(), "kind": kind, **data}
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
    recent_tasks = data.get("recent_tasks", [])
    if not isinstance(recent_tasks, list):
        recent_tasks = []
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
        current_attempt=int(data.get("current_attempt", 0)),
        last_result=str(data.get("last_result", "")),
        next_task=str(data.get("next_task", "")),
        recent_tasks=[str(item) for item in recent_tasks if isinstance(item, str)][-10:],
    )


def acquire_run_lock() -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    if PID_PATH.exists():
        try:
            pid = int(PID_PATH.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            pid = 0
        if pid > 0:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                pass
            except PermissionError as exc:
                raise RunnerError(f"another PASI overnight runner appears active (PID {pid})") from exc
            except OSError:
                pass
            else:
                raise RunnerError(f"another PASI overnight runner is already active (PID {pid})")
    PID_PATH.write_text(f"{os.getpid()}\n", encoding="utf-8")


def release_run_lock() -> None:
    try:
        PID_PATH.unlink()
    except FileNotFoundError:
        pass


def run_command(command: list[str], cwd: Path, *, timeout: float) -> tuple[int, str]:
    try:
        result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)
    output = ((result.stdout or "") + (result.stderr or "")).strip()
    return result.returncode, output[-MAX_COMMAND_OUTPUT_CHARS:]


def health(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=3.0) as response:
            return 200 <= response.status < 300
    except (OSError, urllib.error.URLError):
        return False


def ensure_local_services() -> list[subprocess.Popen[str]]:
    children: list[subprocess.Popen[str]] = []
    if not health(BRIDGE_HEALTH_URL):
        log_event("service_start", service="bridge")
        children.append(subprocess.Popen([sys.executable, "-m", "automation.orchestrator.bridge"], cwd=REPOSITORY_ROOT))
    if not health(CONTROLLER_SERVER_HEALTH_URL):
        log_event("service_start", service="controller_distribution")
        children.append(subprocess.Popen([sys.executable, "scripts/pasi_controller_server.py"], cwd=REPOSITORY_ROOT))
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        if health(BRIDGE_HEALTH_URL) and health(CONTROLLER_SERVER_HEALTH_URL):
            return children
        time.sleep(0.5)
    raise RunnerError("PASI local services did not become healthy on ports 8765 and 8766")


def ensure_worktree(worktree: Path, branch: str, *, resume: bool) -> None:
    worktree.parent.mkdir(parents=True, exist_ok=True)
    if not (worktree / ".git").exists():
        code, output = run_command(["git", "worktree", "add", "-B", branch, str(worktree), "origin/main"], REPOSITORY_ROOT, timeout=60.0)
        if code != 0:
            raise RunnerError(f"could not create overnight worktree: {output}")
        return

    code, output = run_command(["git", "status", "--porcelain"], worktree, timeout=15.0)
    if code != 0:
        raise RunnerError(f"could not inspect overnight worktree: {output}")
    if output:
        if not resume:
            raise RunnerError("overnight worktree contains local changes; refusing to overwrite them")
        log_event("resume_cleanup", reason="discarding uncommitted interrupted-task changes in dedicated overnight worktree")
        reset_code, reset_output = run_command(["git", "reset", "--hard", "HEAD"], worktree, timeout=60.0)
        clean_code, clean_output = run_command(["git", "clean", "-fd"], worktree, timeout=60.0)
        if reset_code != 0 or clean_code != 0:
            raise RunnerError(f"could not recover overnight worktree: {reset_output or clean_output}")
    code, output = run_command(["git", "checkout", branch], worktree, timeout=30.0)
    if code != 0:
        raise RunnerError(f"could not select overnight branch: {output}")


def validate_patch_paths(patch: str, allow_delete: bool) -> None:
    if len(patch.encode("utf-8")) > MAX_PATCH_BYTES:
        raise ValueError("model patch exceeds configured size bound")
    if "new file mode 120000" in patch or "new file mode 160000" in patch:
        raise ValueError("symlink and submodule additions are not allowed in unattended patches")
    matches = DIFF_PATH_RE.findall(patch)
    if not matches:
        raise ValueError("model response did not contain a unified git patch")
    for old_path, new_path in matches:
        for raw_path in (old_path, new_path):
            if raw_path == "/dev/null":
                continue
            path = raw_path.replace("\\", "/")
            parts = Path(path).parts
            if path.startswith("/") or ".." in parts:
                raise ValueError(f"unsafe patch path: {raw_path}")
            if any(part in FORBIDDEN_PATH_PARTS for part in parts):
                raise ValueError(f"forbidden patch path: {raw_path}")
            if any(pattern.search(path) for pattern in FORBIDDEN_PATH_PATTERNS):
                raise ValueError(f"forbidden credential/secret path: {raw_path}")
        if not allow_delete and (old_path == "/dev/null" or new_path == "/dev/null"):
            raise ValueError("patch uses /dev/null; set PASI_RESULT_ALLOW_DELETE: true only when deletion is necessary")


def parse_response(response: str) -> tuple[str, str, str, str, bool, dict[str, str]]:
    values: dict[str, str] = {}
    for name, pattern in MARKERS.items():
        match = pattern.search(response)
        if match:
            values[name] = match.group(1).strip()
    allow_delete = bool(re.search(r"^PASI_RESULT_ALLOW_DELETE:\s*true$", response, re.MULTILINE | re.IGNORECASE))
    if PATCH_BEGIN in response and PATCH_END in response:
        patch = response.split(PATCH_BEGIN, 1)[1].split(PATCH_END, 1)[0].strip()
    else:
        patch = ""
    return values.get("status", "blocked").lower(), values.get("summary", ""), values.get("next_task", ""), patch, allow_delete, values


def completion_contract_is_satisfied(status: str, values: dict[str, str]) -> bool:
    return (
        status == "complete"
        and values.get("requirements", "").lower() == "complete"
        and values.get("limitations", "").lower() in {"handled", "none", "not_applicable"}
        and values.get("research", "").lower() in {"performed", "not_applicable"}
        and values.get("ux", "").lower() in {"verified", "not_applicable"}
        and values.get("backend", "").lower() in {"verified", "not_applicable"}
        and bool(values.get("evidence", "").strip())
    )


def build_task_prompt(task: str, state: RunnerState, repair_output: str) -> str:
    repair = f"\nPREVIOUS FAILURE EVIDENCE:\n{repair_output[-12_000:]}\n" if repair_output else ""
    return f"""You are the implementation engineer inside an unattended PASI overnight coding run.

CURRENT TASK:
{task}

RUN CONTEXT:
- Run ID: {state.run_id}
- Task number: {state.task_number}
- Attempt: {state.current_attempt}/{MAX_TASK_ATTEMPTS}
- Work branch: {state.branch}
- Changes must be made only through the patch below.
- The repository is private; use the connected GitHub app when repository context is required.

COMPLETION CONTRACT:
A task is complete only when all stated requirements are implemented; applicable limitations have concrete workarounds or are genuinely not applicable; useful additional features have been researched and implemented when appropriate; UX is functioning and aesthetically coherent for the scope or not applicable; backend behavior is functioning or not applicable; and reproducible evidence supports the result.
For UX work, compare against relevant current products/sites when appropriate and validate actual behavior rather than screenshots alone.
Do not claim tests, research, changes, or functionality without evidence.

OUTPUT CONTRACT — return every marker exactly once:
PASI_RESULT_STATUS: complete|needs_revision|blocked
PASI_RESULT_SUMMARY: one concise sentence
PASI_RESULT_NEXT_TASK: one concrete high-value next task
PASI_RESULT_REQUIREMENTS: complete
PASI_RESULT_LIMITATIONS: handled|none|not_applicable
PASI_RESULT_RESEARCH: performed|not_applicable
PASI_RESULT_UX: verified|not_applicable
PASI_RESULT_BACKEND: verified|not_applicable
PASI_RESULT_EVIDENCE: concise evidence summary including tests/verification
PASI_RESULT_ALLOW_DELETE: true|false
PASI_RESULT_PATCH_BEGIN
<one unified git diff that implements the task>
PASI_RESULT_PATCH_END

The patch must apply with `git apply`, stay inside this repository, and contain no symlink or submodule additions. Do not emit shell commands as the change mechanism.
{repair}"""


def choose_next_task(state: RunnerState, suggested: str) -> str:
    candidate = re.sub(r"\s+", " ", suggested).strip()
    recent = {item.lower() for item in state.recent_tasks[-8:]}
    if candidate and candidate.lower() not in recent:
        return candidate
    for fallback in BACKLOG:
        if fallback.lower() not in recent:
            return fallback
    return BACKLOG[state.completed_tasks % len(BACKLOG)]


def select_next_task(state: RunnerState) -> str:
    prompt = f"""Choose one concrete next PASI implementation task after this verified result: {state.last_result}\nDo not repeat these recent tasks: {state.recent_tasks[-8:]}\nReturn exactly one line: PASI_NEXT_TASK: <task>"""
    code, output = run_command(
        [sys.executable, "scripts/pasi_chat.py", prompt, "--github", "always", "--timeout", "600"],
        Path(state.worktree),
        timeout=660.0,
    )
    if code == 0:
        match = re.search(r"PASI_NEXT_TASK:\s*(.+)", output)
        if match:
            return choose_next_task(state, match.group(1))
    return choose_next_task(state, "")


def request_task_response(task: str, state: RunnerState, repair_output: str) -> tuple[int, str]:
    prompt = build_task_prompt(task, state, repair_output)
    return run_command(
        [sys.executable, "scripts/pasi_chat.py", prompt, "--github", "always", "--timeout", "900"],
        Path(state.worktree),
        timeout=960.0,
    )


def apply_patch_and_verify(worktree: Path, patch: str, allow_delete: bool) -> str:
    validate_patch_paths(patch, allow_delete)
    code, output = run_command(["git", "apply", "--check", "--whitespace=nowarn"], worktree, timeout=60.0)
    if code != 0:
        raise RunnerError(f"git apply --check failed:\n{output}")
    code, output = run_command(["git", "apply", "--whitespace=nowarn"], worktree, timeout=60.0)
    if code != 0:
        raise RunnerError(f"git apply failed:\n{output}")
    code, output = run_command(["bash", "scripts/check_all.sh"], worktree, timeout=900.0)
    if code != 0:
        raise RunnerError(f"canonical validation failed:\n{output}")
    status_code, status_output = run_command(["git", "status", "--porcelain"], worktree, timeout=30.0)
    if status_code != 0 or not status_output:
        raise RunnerError("verification passed but no repository changes were produced")
    return output


def commit_and_push(worktree: Path, branch: str, task: str, push: bool) -> str:
    message = re.sub(r"[^A-Za-z0-9 .:_/-]+", "", task).strip()[:65] or "overnight PASI task"
    code, output = run_command(["git", "add", "-A"], worktree, timeout=30.0)
    if code != 0:
        raise RunnerError(f"git add failed: {output}")
    code, output = run_command(["git", "diff", "--cached", "--quiet"], worktree, timeout=30.0)
    if code == 0:
        raise RunnerError("task produced no staged changes")
    code, output = run_command(["git", "commit", "-m", f"pasi: {message}"], worktree, timeout=120.0)
    if code != 0:
        raise RunnerError(f"git commit failed: {output}")
    code, commit = run_command(["git", "rev-parse", "HEAD"], worktree, timeout=15.0)
    if code != 0:
        raise RunnerError(f"could not read commit: {commit}")
    if push:
        code, output = run_command(["git", "push", "--set-upstream", "origin", branch], worktree, timeout=180.0)
        if code != 0:
            raise RunnerError(f"git push failed: {output}")
    return commit


def handle_signal(signum: int, _frame: object) -> None:
    global STOP_REQUESTED
    STOP_REQUESTED = True
    log_event("stop_requested", signal=signum)


def run_loop(state: RunnerState, *, push: bool) -> None:
    repair_output = ""
    controller_backoff = 5.0
    while not STOP_REQUESTED and utc_now() < datetime.fromisoformat(state.deadline_at):
        state.task_number += 1
        state.current_attempt = 0
        state.current_task = re.sub(r"\s+", " ", state.current_task).strip()
        if not state.current_task:
            state.current_task = select_next_task(state)
        state.recent_tasks.append(state.current_task)
        state.recent_tasks = state.recent_tasks[-10:]
        save_state(state)
        log_event("task_started", task_number=state.task_number, task=state.current_task)

        finished = False
        while state.current_attempt < MAX_TASK_ATTEMPTS and not STOP_REQUESTED:
            if utc_now() >= datetime.fromisoformat(state.deadline_at):
                return
            state.current_attempt += 1
            save_state(state)
            code, response = request_task_response(state.current_task, state, repair_output)
            if code != 0:
                message = response or "ChatGPT invocation failed without diagnostic output"
                if "browser controller is not reporting a live heartbeat" in message.lower():
                    time.sleep(min(controller_backoff, MAX_CONTROLLER_BACKOFF_SECONDS))
                    controller_backoff = min(controller_backoff * 2.0, MAX_CONTROLLER_BACKOFF_SECONDS)
                    state.current_attempt -= 1
                    continue
                repair_output = message
                log_event("task_invocation_failed", task_number=state.task_number, attempt=state.current_attempt, error=message[-6000:])
                continue

            controller_backoff = 5.0
            status, summary, next_task, patch, allow_delete, values = parse_response(response)
            contract_ok = completion_contract_is_satisfied(status, values)
            log_event("task_response", task_number=state.task_number, attempt=state.current_attempt, status=status, contract_ok=contract_ok, summary=summary, evidence=values, patch_bytes=len(patch.encode("utf-8")))
            if not patch or not contract_ok:
                repair_output = summary or "completion contract not satisfied or patch missing"
                continue

            try:
                verification = apply_patch_and_verify(Path(state.worktree), patch, allow_delete)
            except Exception as exc:
                repair_output = str(exc)
                log_event("task_verification_failed", task_number=state.task_number, attempt=state.current_attempt, error=repair_output[-6000:])
                run_command(["git", "reset", "--hard", "HEAD"], Path(state.worktree), timeout=60.0)
                run_command(["git", "clean", "-fd"], Path(state.worktree), timeout=60.0)
                continue

            commit = commit_and_push(Path(state.worktree), state.branch, state.current_task, push)
            state.completed_tasks += 1
            state.last_result = summary or values.get("evidence", "validated task completed")
            state.next_task = choose_next_task(state, next_task)
            state.current_attempt = 0
            save_state(state)
            log_event("task_completed", task_number=state.task_number, commit=commit, verification_tail=verification[-4000:], next_task=state.next_task)
            finished = True
            repair_output = ""
            break

        if not finished:
            state.failed_tasks += 1
            state.last_result = repair_output or "task exceeded the bounded retry budget"
            save_state(state)
            log_event("task_failed", task_number=state.task_number, error=state.last_result[-6000:])
            run_command(["git", "reset", "--hard", "HEAD"], Path(state.worktree), timeout=60.0)
            run_command(["git", "clean", "-fd"], Path(state.worktree), timeout=60.0)
            state.current_task = "Recover the blocked PASI task by diagnosing its verified failure and implementing a different concrete workaround."
            repair_output = state.last_result
            continue

        state.current_task = state.next_task
        save_state(state)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run PASI autonomously for 8-12 hours with bounded task continuation.")
    parser.add_argument("--hours", type=float, default=DEFAULT_DURATION_HOURS)
    parser.add_argument("--task", default="Optimize PASI automation so the most work is achieved with the least repeated human input while preserving safe human approval boundaries and making the computer-use control plane reliable for long unattended operation.")
    parser.add_argument("--worktree", type=Path, default=DEFAULT_WORKTREE)
    parser.add_argument("--branch", default=f"pasi/overnight-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--no-push", action="store_true")
    args = parser.parse_args()
    if not (MIN_DURATION_HOURS <= args.hours <= MAX_DURATION_HOURS):
        parser.error(f"--hours must be between {MIN_DURATION_HOURS:g} and {MAX_DURATION_HOURS:g}")

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)
    children: list[subprocess.Popen[str]] = []
    acquire_run_lock()
    try:
        code, output = run_command(["git", "fetch", "origin", "main"], REPOSITORY_ROOT, timeout=120.0)
        if code != 0:
            raise RunnerError(f"git fetch origin main failed: {output}")

        persisted = load_state() if args.resume else None
        if persisted is not None and utc_now() < datetime.fromisoformat(persisted.deadline_at):
            state = persisted
            log_event("run_resumed", **state.to_dict())
            resume = True
        else:
            started = utc_now()
            state = RunnerState(
                run_id=f"overnight-{uuid.uuid4().hex}",
                started_at=started.isoformat(),
                deadline_at=(started + timedelta(hours=args.hours)).isoformat(),
                worktree=str(args.worktree.expanduser().resolve()),
                branch=args.branch,
                current_task=args.task,
            )
            save_state(state)
            log_event("run_started", **state.to_dict(), push=not args.no_push)
            resume = False

        ensure_worktree(Path(state.worktree), state.branch, resume=resume)
        children = ensure_local_services()
        run_loop(state, push=not args.no_push)
        state.last_result = "stopped by operator" if STOP_REQUESTED else "overnight deadline reached"
        save_state(state)
        log_event("run_finished", completed_tasks=state.completed_tasks, failed_tasks=state.failed_tasks, reason=state.last_result)
        return 0
    except Exception as exc:
        log_event("run_failed", error=str(exc))
        return 1
    finally:
        release_run_lock()
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
