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
from typing import Any, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = REPO_ROOT / ".runtime" / "overnight"
STATE_PATH = RUNTIME_DIR / "state.json"
EVENT_LOG = RUNTIME_DIR / "events.jsonl"
PID_PATH = RUNTIME_DIR / "runner.pid"
DEFAULT_WORKTREE = Path.home() / ".pasi-worktrees" / "personal-ai-system-overnight"
DEFAULT_HOURS = 10.0
MIN_HOURS = 8.0
MAX_HOURS = 12.0
BRIDGE_HEALTH = "http://127.0.0.1:8765/health"
CONTROLLER_DISTRIBUTION_HEALTH = "http://127.0.0.1:8766/health"
MAX_PATCH_BYTES = 250_000
MAX_OUTPUT_CHARS = 20_000
MAX_ATTEMPTS = 3
MAX_CONTROLLER_BACKOFF = 60.0

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
    "repository_progress": re.compile(r"^PASI_RESULT_REPOSITORY_PROGRESS:\s*(.+)$", re.MULTILINE),
}

BACKLOG = (
    "Audit the ChatGPT computer-use control path end to end and remove avoidable polling, duplicated state, and brittle browser assumptions while preserving current tests and safety boundaries.",
    "Harden PASI task continuation so completed work deterministically produces the next highest-value task from verified repository gaps, with bounded retries and persistent recovery state.",
    "Improve ChatGPT controller browser compatibility and response extraction using current DOM evidence patterns while keeping provider-specific selectors isolated to the controller.",
    "Improve engineering evidence and verification so completion is based on reproducible tests, diagnostics, and repository state instead of model claims.",
    "Improve PASI UX/UI for automation state, task progress, failures, verification evidence, and safe human intervention while keeping backend behavior aligned.",
)

STOP = False


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


class OvernightError(RuntimeError):
    pass


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def log_event(kind: str, **data: Any) -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    event = {"timestamp": now_utc().isoformat(), "kind": kind, **data}
    with EVENT_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    print(json.dumps(event, ensure_ascii=False), flush=True)


def save_state(state: RunnerState) -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_state() -> RunnerState | None:
    try:
        value = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict):
        return None
    try:
        return RunnerState(
            run_id=str(value["run_id"]),
            started_at=str(value["started_at"]),
            deadline_at=str(value["deadline_at"]),
            worktree=str(value["worktree"]),
            branch=str(value["branch"]),
            current_task=str(value["current_task"]),
            task_number=int(value.get("task_number", 0)),
            completed_tasks=int(value.get("completed_tasks", 0)),
            failed_tasks=int(value.get("failed_tasks", 0)),
            current_attempt=int(value.get("current_attempt", 0)),
            last_result=str(value.get("last_result", "")),
            next_task=str(value.get("next_task", "")),
            recent_tasks=[str(item) for item in value.get("recent_tasks", []) if isinstance(item, str)][-10:],
        )
    except (KeyError, TypeError, ValueError):
        return None


def acquire_lock() -> None:
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
                raise OvernightError(f"another overnight runner may be active (PID {pid})") from exc
            except OSError:
                pass
            else:
                raise OvernightError(f"another overnight runner is already active (PID {pid})")
    PID_PATH.write_text(f"{os.getpid()}\n", encoding="utf-8")


def release_lock() -> None:
    try:
        PID_PATH.unlink()
    except FileNotFoundError:
        pass


def command(
    command: list[str],
    cwd: Path,
    *,
    timeout: float,
    input_text: str | None = None,
) -> tuple[int, str]:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            input=input_text,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)
    output = ((result.stdout or "") + (result.stderr or "")).strip()
    return result.returncode, output[-MAX_OUTPUT_CHARS:]


def healthy(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=3.0) as response:
            return 200 <= response.status < 300
    except (OSError, urllib.error.URLError):
        return False


def ensure_services() -> list[subprocess.Popen[bytes]]:
    children: list[subprocess.Popen[bytes]] = []
    if not healthy(BRIDGE_HEALTH):
        log_event("service_start", service="bridge")
        children.append(subprocess.Popen([sys.executable, "-m", "automation.orchestrator.bridge"], cwd=REPO_ROOT))
    if not healthy(CONTROLLER_DISTRIBUTION_HEALTH):
        log_event("service_start", service="controller_distribution")
        children.append(subprocess.Popen([sys.executable, "scripts/pasi_controller_server.py"], cwd=REPO_ROOT))
    deadline = time.monotonic() + 20.0
    while time.monotonic() < deadline:
        if healthy(BRIDGE_HEALTH) and healthy(CONTROLLER_DISTRIBUTION_HEALTH):
            return children
        time.sleep(0.5)
    raise OvernightError("local PASI bridge/distribution services did not become healthy")


def ensure_worktree(path: Path, branch: str, *, resume: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not (path / ".git").exists():
        code, output = command(["git", "worktree", "add", "-B", branch, str(path), "origin/main"], REPO_ROOT, timeout=60.0)
        if code != 0:
            raise OvernightError(f"could not create overnight worktree: {output}")
        return
    code, output = command(["git", "status", "--porcelain"], path, timeout=15.0)
    if code != 0:
        raise OvernightError(f"could not inspect overnight worktree: {output}")
    if output:
        if not resume:
            raise OvernightError("overnight worktree contains local changes")
        log_event("resume_cleanup", reason="discarding uncommitted interrupted-task changes in dedicated worktree")
        for cleanup in (["git", "reset", "--hard", "HEAD"], ["git", "clean", "-fd"]):
            cleanup_code, cleanup_output = command(cleanup, path, timeout=60.0)
            if cleanup_code != 0:
                raise OvernightError(f"could not recover overnight worktree: {cleanup_output}")
    code, output = command(["git", "checkout", branch], path, timeout=30.0)
    if code != 0:
        raise OvernightError(f"could not select overnight branch: {output}")


def validate_patch_paths(patch: str, allow_delete: bool) -> None:
    if len(patch.encode("utf-8")) > MAX_PATCH_BYTES:
        raise ValueError("model patch exceeds configured size bound")
    if "new file mode 120000" in patch or "new file mode 160000" in patch:
        raise ValueError("symlink and submodule additions are not allowed in unattended patches")
    matches = re.findall(r"^diff --git a/(.+) b/(.+)$", patch, re.MULTILINE)
    if not matches:
        raise ValueError("model response did not contain a unified git diff")
    for old_path, new_path in matches:
        for path_value in (old_path, new_path):
            if path_value == "/dev/null":
                continue
            normalized = path_value.replace("\\", "/")
            parts = Path(normalized).parts
            if normalized.startswith("/") or ".." in parts:
                raise ValueError(f"unsafe patch path: {path_value}")
            if any(part in {".git", ".env", ".env.local", ".env.production"} for part in parts):
                raise ValueError(f"forbidden patch path: {path_value}")
            if any(pattern.search(normalized) for pattern in (
                re.compile(r"(^|/)(id_rsa|id_ed25519|authorized_keys)$", re.IGNORECASE),
                re.compile(r"(^|/)(credentials|secrets?)(\.|/|$)", re.IGNORECASE),
            )):
                raise ValueError(f"forbidden credential/secret path: {path_value}")
        if new_path == "/dev/null" and not allow_delete:
            raise ValueError("file deletion requires PASI_RESULT_ALLOW_DELETE: true")


def normalize_patch(patch: str) -> str:
    """Convert common Markdown-wrapped model diffs into a plain unified diff."""
    normalized = patch.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return ""
    lines = normalized.splitlines()
    try:
        start = next(index for index, line in enumerate(lines) if line.startswith("diff --git "))
    except StopIteration:
        return normalized
    lines = lines[start:]
    for index, line in enumerate(lines):
        if line.strip().startswith("```"):
            lines = lines[:index]
            break
    return "\n".join(lines).strip() + "\n"


def parse_response(response: str) -> tuple[str, str, str, str, bool, dict[str, str]]:
    values: dict[str, str] = {}
    for key, pattern in MARKERS.items():
        match = pattern.search(response)
        if match:
            values[key] = match.group(1).strip()
    allow_delete = bool(re.search(r"^PASI_RESULT_ALLOW_DELETE:\s*true$", response, re.MULTILINE | re.IGNORECASE))
    raw_patch = response.split(PATCH_BEGIN, 1)[1].split(PATCH_END, 1)[0] if PATCH_BEGIN in response and PATCH_END in response else ""
    patch = normalize_patch(raw_patch)
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


def repository_worktree_is_clean(worktree: Path) -> bool:
    code, status = command(["git", "status", "--porcelain", "--untracked-files=all"], worktree, timeout=30.0)
    return code == 0 and not status.strip()


def no_change_completion_is_satisfied(
    worktree: Path,
    status: str,
    next_task: str,
    patch: str,
    values: dict[str, str],
) -> bool:
    return (
        completion_contract_is_satisfied(status, values)
        and not patch
        and values.get("repository_progress", "").lower() == "stopped"
        and bool(next_task.strip())
        and repository_worktree_is_clean(worktree)
    )


def continuation_directive(state: RunnerState, task: str) -> str:
    roadmap = "\n".join(f"- {item}" for item in BACKLOG)
    recent = "\n".join(f"- {item}" for item in state.recent_tasks[-8:]) or "- none recorded"
    return f"""TASK CONTINUATION / ANTI-LOOP POLICY:
- First inspect the current repository state and recent commits before deciding whether the CURRENT TASK is still incomplete.
- IF the CURRENT TASK is already satisfied by verified repository changes and evidence, THEN do not re-implement it, do not make cosmetic duplicate changes, and do not ask the human what to do next; immediately work on the next incomplete roadmap item below.
- IF the CURRENT TASK is not yet satisfied, THEN continue it and use a materially different approach when PREVIOUS FAILURE EVIDENCE shows the prior approach failed.
- A response-repair prompt repairs the response contract; it does not restart an implementation that is already verified.
- After a verified completion, set PASI_RESULT_NEXT_TASK to the next incomplete, high-value item rather than repeating CURRENT TASK.
- IF the CURRENT TASK is already satisfied and another implementation pass would make no repository changes, THEN report PASI_RESULT_REPOSITORY_PROGRESS: stopped with an empty patch and immediately advance to PASI_RESULT_NEXT_TASK; never invent a cosmetic patch just to keep the task alive.
- IF the CURRENT TASK still has a concrete repository change to make, THEN report PASI_RESULT_REPOSITORY_PROGRESS: changed and provide the required patch.
- IF the listed roadmap items are already covered by verified recent work, THEN revisit the repository for the next concrete gap and make that the next task instead of repeating an old task.
- Never wait for an additional human instruction merely because the current task completed; the persisted runner state is the continuation authority.
ROADMAP:
{roadmap}
RECENT TASKS:
{recent}

CURRENT TASK:
{task}"""

def build_prompt(task: str, state: RunnerState, failure: str = "") -> str:
    previous = f"\nPREVIOUS FAILURE EVIDENCE:\n{failure[-12_000:]}\n" if failure else ""
    return f"""You are the implementation engineer inside an unattended PASI overnight coding run.

CURRENT TASK:
{task}

RUN CONTEXT:
- Run: {state.run_id}
- Task: {state.task_number}
- Attempt: {state.current_attempt}/{MAX_ATTEMPTS}
- Branch: {state.branch}
- Worktree: isolated and controlled by PASI
- The repository is private; use the connected GitHub app when source/history context is required.

{continuation_directive(state, task)}

COMPLETION CONTRACT:
Do not mark complete until every stated requirement is implemented; relevant limitations have a concrete workaround or are genuinely not applicable; useful additional research/features have been implemented when appropriate; UX is working and aesthetically coherent or not applicable; backend behavior is working or not applicable; and reproducible evidence supports the result.

OUTPUT — return each marker exactly once:
PASI_RESULT_STATUS: complete|needs_revision|blocked
PASI_RESULT_SUMMARY: one concise sentence
PASI_RESULT_NEXT_TASK: one concrete high-value next task
PASI_RESULT_REQUIREMENTS: complete
PASI_RESULT_LIMITATIONS: handled|none|not_applicable
PASI_RESULT_RESEARCH: performed|not_applicable
PASI_RESULT_UX: verified|not_applicable
PASI_RESULT_BACKEND: verified|not_applicable
PASI_RESULT_EVIDENCE: concise tests/verification evidence
PASI_RESULT_REPOSITORY_PROGRESS: changed|stopped
PASI_RESULT_ALLOW_DELETE: true|false
PASI_RESULT_PATCH_BEGIN
<one unified git diff, plain text only; do not wrap the diff in Markdown code fences or add prose inside the patch markers>
PASI_RESULT_PATCH_END

The patch must apply with git apply, modify only repository files, and contain no symlink or submodule additions. Do not use shell commands as the change mechanism.
{previous}"""


def choose_next_task(state: RunnerState, suggested: str) -> str:
    candidate = re.sub(r"\s+", " ", suggested).strip()
    recent = {item.lower() for item in state.recent_tasks[-8:]}
    configured = {item.lower(): item for item in BACKLOG}
    if candidate and candidate.lower() in configured and candidate.lower() not in recent:
        return configured[candidate.lower()]
    for fallback in BACKLOG:
        if fallback.lower() not in recent:
            return fallback
    return BACKLOG[state.completed_tasks % len(BACKLOG)]


def invoke_chat(task: str, state: RunnerState, failure: str) -> tuple[int, str]:
    return command(
        [sys.executable, "scripts/pasi_chat.py", build_prompt(task, state, failure), "--github", "always", "--timeout", "900"],
        Path(state.worktree),
        timeout=960.0,
    )


def verify_patch(worktree: Path, patch: str, allow_delete: bool) -> str:
    normalized_patch = normalize_patch(patch)
    validate_patch_paths(normalized_patch, allow_delete)
    code, output = command(
        ["git", "apply", "--check", "--whitespace=nowarn"],
        worktree,
        timeout=60.0,
        input_text=normalized_patch,
    )
    if code != 0:
        raise OvernightError(f"git apply --check failed:\n{output}")
    code, output = command(
        ["git", "apply", "--whitespace=nowarn"],
        worktree,
        timeout=60.0,
        input_text=normalized_patch,
    )
    if code != 0:
        raise OvernightError(f"git apply failed:\n{output}")
    code, output = command(["bash", "scripts/check_all.sh"], worktree, timeout=900.0)
    if code != 0:
        raise OvernightError(f"canonical validation failed:\n{output}")
    code, status = command(["git", "status", "--porcelain"], worktree, timeout=30.0)
    if code != 0 or not status:
        raise OvernightError("verification passed but no repository changes remain")
    return output


def patch_paths_from_diff(patch: str) -> list[str]:
    paths: list[str] = []
    for old_path, new_path in re.findall(r"^diff --git a/(.+) b/(.+)$", patch, re.MULTILINE):
        for value in (old_path, new_path):
            if value != "/dev/null" and value not in paths:
                paths.append(value)
    return paths


def commit_and_push(
    worktree: Path,
    branch: str,
    task: str,
    push: bool,
    *,
    paths: Sequence[str] | None = None,
) -> str:
    if paths:
        code, output = command(["git", "add", "--", *paths], worktree, timeout=30.0)
    else:
        code, output = command(["git", "add", "-A"], worktree, timeout=30.0)
    if code != 0:
        raise OvernightError(f"git add failed: {output}")
    code, output = command(["git", "diff", "--cached", "--quiet"], worktree, timeout=30.0)
    if code == 0:
        raise OvernightError("task completed without producing a commit")
    message = re.sub(r"[^A-Za-z0-9 .:_/-]+", "", task).strip()[:65] or "overnight PASI task"
    code, output = command(
        [
            "git",
            "-c", "user.name=PASI Automation",
            "-c", "user.email=pasi@local.invalid",
            "commit", "-m", f"pasi: {message}",
        ],
        worktree,
        timeout=120.0,
    )
    if code != 0:
        raise OvernightError(f"git commit failed: {output}")
    code, commit = command(["git", "rev-parse", "HEAD"], worktree, timeout=15.0)
    if code != 0:
        raise OvernightError(f"could not read commit: {commit}")
    if push:
        code, output = command(["git", "push", "--set-upstream", "origin", branch], worktree, timeout=180.0)
        if code != 0:
            raise OvernightError(f"git push failed: {output}")
    return commit


def on_signal(signum: int, _frame: object) -> None:
    global STOP
    STOP = True
    log_event("stop_requested", signal=signum)


def run(state: RunnerState, *, push: bool) -> None:
    failure = ""
    backoff = 5.0
    while not STOP and now_utc() < datetime.fromisoformat(state.deadline_at):
        state.task_number += 1
        state.current_attempt = 0
        state.current_task = re.sub(r"\s+", " ", state.current_task).strip()
        if not state.current_task:
            state.current_task = choose_next_task(state, "")
        state.recent_tasks.append(state.current_task)
        state.recent_tasks = state.recent_tasks[-10:]
        save_state(state)
        log_event("task_started", task_number=state.task_number, task=state.current_task)

        finished = False
        while state.current_attempt < MAX_ATTEMPTS and not STOP:
            if now_utc() >= datetime.fromisoformat(state.deadline_at):
                return
            state.current_attempt += 1
            save_state(state)
            code, response = invoke_chat(state.current_task, state, failure)
            if code != 0:
                failure = response or "ChatGPT invocation failed without diagnostic output"
                if "browser controller is not reporting a live heartbeat" in failure.lower():
                    time.sleep(min(backoff, MAX_CONTROLLER_BACKOFF))
                    backoff = min(backoff * 2.0, MAX_CONTROLLER_BACKOFF)
                    state.current_attempt -= 1
                    continue
                log_event("task_invocation_failed", task_number=state.task_number, attempt=state.current_attempt, error=failure[-6000:])
                continue

            backoff = 5.0
            status, summary, next_task, patch, allow_delete, values = parse_response(response)
            contract_ok = completion_contract_is_satisfied(status, values)
            log_event("task_response", task_number=state.task_number, attempt=state.current_attempt, status=status, contract_ok=contract_ok, summary=summary, evidence=values)
            if contract_ok and no_change_completion_is_satisfied(
                Path(state.worktree), status, next_task, patch, values
            ):
                state.completed_tasks += 1
                state.last_result = summary or values.get("evidence", "validated task already satisfied; no repository change remained")
                state.next_task = choose_next_task(state, next_task)
                state.current_attempt = 0
                save_state(state)
                log_event(
                    "task_completed_no_change",
                    task_number=state.task_number,
                    reason="task already satisfied and repository remained clean",
                    next_task=state.next_task,
                )
                finished = True
                failure = ""
                break
            if not patch or not contract_ok:
                failure = summary or "completion contract not satisfied or implementation patch missing"
                continue
            try:
                verification = verify_patch(Path(state.worktree), patch, allow_delete)
                commit = commit_and_push(Path(state.worktree), state.branch, state.current_task, push, paths=patch_paths_from_diff(patch))
            except Exception as exc:
                failure = str(exc)
                log_event("task_verification_failed", task_number=state.task_number, attempt=state.current_attempt, error=failure[-6000:])
                command(["git", "reset", "--hard", "HEAD"], Path(state.worktree), timeout=60.0)
                command(["git", "clean", "-fd"], Path(state.worktree), timeout=60.0)
                continue

            state.completed_tasks += 1
            state.last_result = summary or values.get("evidence", "validated task completed")
            state.next_task = choose_next_task(state, next_task)
            state.current_attempt = 0
            save_state(state)
            log_event("task_completed", task_number=state.task_number, commit=commit, verification=verification[-4000:], next_task=state.next_task)
            finished = True
            failure = ""
            break

        if not finished:
            state.failed_tasks += 1
            state.last_result = failure or "task exceeded bounded retry budget"
            state.current_task = "Recover the blocked PASI task by diagnosing its verified failure and implementing a different concrete workaround without repeating the unsuccessful approach."
            state.next_task = ""
            save_state(state)
            log_event("task_failed", task_number=state.task_number, error=state.last_result[-6000:])
            command(["git", "reset", "--hard", "HEAD"], Path(state.worktree), timeout=60.0)
            command(["git", "clean", "-fd"], Path(state.worktree), timeout=60.0)
            continue

        state.current_task = state.next_task
        save_state(state)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run PASI unattended for 8-12 hours with verified task continuation.")
    parser.add_argument("--hours", type=float, default=DEFAULT_HOURS)
    parser.add_argument("--task", default="Optimize PASI automation so the most work is achieved with the least repeated human input while preserving safe human approval boundaries and making the computer-use control plane reliable for long unattended operation.")
    parser.add_argument("--worktree", type=Path, default=DEFAULT_WORKTREE)
    parser.add_argument("--branch", default=f"pasi/overnight-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--no-push", action="store_true")
    args = parser.parse_args()
    if not MIN_HOURS <= args.hours <= MAX_HOURS:
        parser.error(f"--hours must be between {MIN_HOURS:g} and {MAX_HOURS:g}")

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)
    acquire_lock()
    children: list[subprocess.Popen[bytes]] = []
    try:
        code, output = command(["git", "fetch", "origin", "main"], REPO_ROOT, timeout=120.0)
        if code != 0:
            raise OvernightError(f"git fetch origin main failed: {output}")

        saved = load_state() if args.resume else None
        if saved is not None and now_utc() < datetime.fromisoformat(saved.deadline_at):
            state = saved
            resume = True
            log_event("run_resumed", **state.to_dict())
        else:
            started = now_utc()
            state = RunnerState(
                run_id=f"overnight-{uuid.uuid4().hex}",
                started_at=started.isoformat(),
                deadline_at=(started + timedelta(hours=args.hours)).isoformat(),
                worktree=str(args.worktree.expanduser().resolve()),
                branch=args.branch,
                current_task=args.task,
            )
            resume = False
            save_state(state)
            log_event("run_started", **state.to_dict(), push=not args.no_push)

        ensure_worktree(Path(state.worktree), state.branch, resume=resume)
        children = ensure_services()
        run(state, push=not args.no_push)
        state.last_result = "stopped by operator" if STOP else "overnight deadline reached"
        save_state(state)
        log_event("run_finished", completed_tasks=state.completed_tasks, failed_tasks=state.failed_tasks, reason=state.last_result)
        return 0
    except Exception as exc:
        log_event("run_failed", error=str(exc))
        return 1
    finally:
        release_lock()
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
