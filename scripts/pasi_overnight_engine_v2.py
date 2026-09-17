from __future__ import annotations

import argparse
import json
import re
import signal
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from scripts import pasi_overnight_engine as legacy

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = REPO_ROOT / ".runtime" / "overnight"
STATE_PATH = RUNTIME_DIR / "state.json"
EVENT_LOG = RUNTIME_DIR / "events.jsonl"
PID_PATH = RUNTIME_DIR / "runner.pid"
DEFAULT_WORKTREE = legacy.DEFAULT_WORKTREE
DEFAULT_HOURS = legacy.DEFAULT_HOURS
MIN_HOURS = legacy.MIN_HOURS
MAX_HOURS = legacy.MAX_HOURS
MAX_ATTEMPTS = legacy.MAX_ATTEMPTS
MAX_CONTROLLER_BACKOFF = legacy.MAX_CONTROLLER_BACKOFF
BRIDGE_URL = "http://127.0.0.1:8765"
TASK_TIMEOUT_SECONDS = 900.0
WATCHDOG_MAX_AGE_SECONDS = 20.0
MAX_PROVIDER_LIMIT_PAUSES = 2
PROVIDER_BACKOFF_SECONDS = (300.0, 900.0)
AUTOMATION_TASKS_PER_GATE = 2

AUTOMATION_TASKS = (
    "Audit the PASI computer-use control plane end to end and implement concrete changes that reduce repeated human input, improve state continuity, improve browser recovery, and preserve all existing safety boundaries.",
    "Harden PASI unattended operation against transient ChatGPT/controller failures: improve bounded retries, response detection, context rollover handling, diagnostics, and recovery without weakening human approval boundaries.",
    "Improve the PASI ChatGPT/Tampermonkey automation itself using repository evidence: reduce brittle DOM assumptions, improve Thinking-state verification, improve provider-limit detection, and keep the controller isolated to provider-specific browser behavior.",
)
ENGINEERING_TASKS = (
    "Improve engineering evidence and verification so completion is based on reproducible tests, diagnostics, repository state, and concrete evidence instead of model claims.",
    "Improve PASI engineering task continuation so verified repository gaps deterministically produce useful next tasks without unnecessary repetition.",
    "Improve PASI UX/UI for engineering state, task progress, failures, verification evidence, and safe human intervention while keeping backend behavior aligned.",
    "Improve provider-neutral engineering adapters and control-plane boundaries so PASI can support additional AI providers without weakening authorization or verification.",
)

MARKERS = {
    **legacy.MARKERS,
    "automation_gate": re.compile(r"^PASI_AUTOMATION_GATE:\s*(proceed_engineering|continue_automation)$", re.MULTILINE | re.IGNORECASE),
    "automation_opportunity": re.compile(r"^PASI_AUTOMATION_OPPORTUNITY:\s*(none|concrete)$", re.MULTILINE | re.IGNORECASE),
    "automation_evidence": re.compile(r"^PASI_AUTOMATION_EVIDENCE:\s*(.+)$", re.MULTILINE),
}

STOP = False


@dataclass
class OvernightState:
    schema_version: int
    run_id: str
    started_at: str
    deadline_at: str
    worktree: str
    branch: str
    phase: str
    current_task: str
    requested_task: str
    task_number: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    current_attempt: int = 0
    automation_tasks_since_gate: int = 0
    automation_gates: int = 0
    provider_limit_pauses: int = 0
    last_result: str = ""
    next_task: str = ""
    stop_reason: str = ""
    recent_tasks: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "started_at": self.started_at,
            "deadline_at": self.deadline_at,
            "worktree": self.worktree,
            "branch": self.branch,
            "phase": self.phase,
            "current_task": self.current_task,
            "requested_task": self.requested_task,
            "task_number": self.task_number,
            "completed_tasks": self.completed_tasks,
            "failed_tasks": self.failed_tasks,
            "current_attempt": self.current_attempt,
            "automation_tasks_since_gate": self.automation_tasks_since_gate,
            "automation_gates": self.automation_gates,
            "provider_limit_pauses": self.provider_limit_pauses,
            "last_result": self.last_result,
            "next_task": self.next_task,
            "stop_reason": self.stop_reason,
            "recent_tasks": self.recent_tasks[-12:],
        }


class OvernightV2Error(RuntimeError):
    pass


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def log_event(kind: str, **data: Any) -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    event = {"timestamp": now_utc().isoformat(), "kind": kind, **data}
    with EVENT_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    print(json.dumps(event, ensure_ascii=False), flush=True)


def save_state(state: OvernightState) -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_state() -> OvernightState | None:
    try:
        value = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict) or int(value.get("schema_version", 0)) != 2:
        return None
    try:
        phase = str(value["phase"])
        if phase not in {"automation", "engineering_os"}:
            return None
        return OvernightState(
            schema_version=2,
            run_id=str(value["run_id"]),
            started_at=str(value["started_at"]),
            deadline_at=str(value["deadline_at"]),
            worktree=str(value["worktree"]),
            branch=str(value["branch"]),
            phase=phase,
            current_task=str(value["current_task"]),
            requested_task=str(value.get("requested_task", "")),
            task_number=int(value.get("task_number", 0)),
            completed_tasks=int(value.get("completed_tasks", 0)),
            failed_tasks=int(value.get("failed_tasks", 0)),
            current_attempt=int(value.get("current_attempt", 0)),
            automation_tasks_since_gate=int(value.get("automation_tasks_since_gate", 0)),
            automation_gates=int(value.get("automation_gates", 0)),
            provider_limit_pauses=int(value.get("provider_limit_pauses", 0)),
            last_result=str(value.get("last_result", "")),
            next_task=str(value.get("next_task", "")),
            stop_reason=str(value.get("stop_reason", "")),
            recent_tasks=[str(item) for item in value.get("recent_tasks", []) if isinstance(item, str)][-12:],
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
                import os
                os.kill(pid, 0)
            except ProcessLookupError:
                pass
            except PermissionError as exc:
                raise OvernightV2Error(f"another overnight runner may be active (PID {pid})") from exc
            except OSError:
                pass
            else:
                raise OvernightV2Error(f"another overnight runner is already active (PID {pid})")
    import os
    PID_PATH.write_text(f"{os.getpid()}\n", encoding="utf-8")


def release_lock() -> None:
    try:
        PID_PATH.unlink()
    except FileNotFoundError:
        pass


def validate_patch_paths(patch: str, allow_delete: bool) -> None:
    legacy.validate_patch_paths(patch, allow_delete)


def parse_v2_response(response: str) -> tuple[str, str, str, str, bool, dict[str, str]]:
    status, summary, next_task, patch, allow_delete, values = legacy.parse_response(response)
    for key, pattern in MARKERS.items():
        match = pattern.search(response)
        if match:
            values[key] = match.group(1).strip().lower()
    return status, summary, next_task, patch, allow_delete, values


def automation_gate_is_satisfied(values: dict[str, str]) -> bool:
    gate = values.get("automation_gate", "")
    opportunity = values.get("automation_opportunity", "")
    evidence = values.get("automation_evidence", "").strip()
    return bool(evidence) and ((gate == "proceed_engineering" and opportunity == "none") or (gate == "continue_automation" and opportunity == "concrete"))


def build_gate_prompt(state: OvernightState) -> str:
    return f"""You are the PASI automation-governance reviewer at an overnight phase boundary.

PASI has just completed {state.automation_tasks_since_gate} automation-improvement task(s). Before PASI is allowed to work on the Engineering OS, determine from repository evidence whether more automation work is concrete and useful.

REPOSITORY: https://github.com/th3-st0v3/personal-ai-system
PHASE: {state.phase}
COMPLETED TASKS: {state.completed_tasks}
RECENT TASKS:
{chr(10).join(state.recent_tasks[-8:]) or 'none'}

Do not invent evidence. Use the public repository as the normal context source and keep Thinking enabled.

Return these markers exactly once:
PASI_RESULT_STATUS: complete|needs_revision|blocked
PASI_RESULT_SUMMARY: one concise sentence
PASI_RESULT_NEXT_TASK: one concrete automation task only when more automation is justified; otherwise state that Engineering OS work can begin
PASI_RESULT_REQUIREMENTS: complete
PASI_RESULT_LIMITATIONS: handled|none|not_applicable
PASI_RESULT_RESEARCH: performed|not_applicable
PASI_RESULT_UX: verified|not_applicable
PASI_RESULT_BACKEND: verified|not_applicable
PASI_RESULT_EVIDENCE: concise evidence supporting the gate
PASI_AUTOMATION_GATE: proceed_engineering|continue_automation
PASI_AUTOMATION_OPPORTUNITY: none|concrete
PASI_AUTOMATION_EVIDENCE: concise evidence for why more automation is or is not useful
PASI_RESULT_ALLOW_DELETE: false
PASI_RESULT_PATCH_BEGIN
<empty patch is allowed for this governance gate>
PASI_RESULT_PATCH_END

A valid transition is only:
- proceed_engineering + none
- continue_automation + concrete
"""


def build_implementation_prompt(task: str, state: OvernightState, failure: str = "") -> str:
    previous = f"\nPREVIOUS FAILURE EVIDENCE:\n{failure[-12_000:]}\n" if failure else ""
    return f"""You are the implementation engineer inside an unattended PASI overnight coding run.

CURRENT TASK:
{task}

PHASE:
{state.phase}

RUN CONTEXT:
- Run: {state.run_id}
- Task: {state.task_number}
- Attempt: {state.current_attempt}/{MAX_ATTEMPTS}
- Branch: {state.branch}
- Worktree: isolated and controlled by PASI
- Canonical public repository: https://github.com/th3-st0v3/personal-ai-system
- Thinking is required for every task.
- The public GitHub repository is the default context source.
- The ChatGPT GitHub app is only an explicit fallback, not a default requirement.

COMPLETION CONTRACT:
Do not mark complete until the stated requirement is implemented and reproducible evidence supports it. Do not claim that files changed or tests passed without evidence.

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
PASI_RESULT_ALLOW_DELETE: true|false
PASI_RESULT_PATCH_BEGIN
<one unified git diff>
PASI_RESULT_PATCH_END

The patch must apply with git apply, modify only repository files, and contain no symlink or submodule additions. Do not use shell commands as the change mechanism.
{previous}"""


def choose_unique(candidates: tuple[str, ...], state: OvernightState) -> str:
    recent = {item.lower() for item in state.recent_tasks[-12:]}
    for candidate in candidates:
        if candidate.lower() not in recent:
            return candidate
    return candidates[state.completed_tasks % len(candidates)]


def command_with_output(command: list[str], cwd: Path, timeout: float) -> tuple[int, str]:
    return legacy.command(command, cwd, timeout=timeout)


def invoke_chat(task: str, state: OvernightState, failure: str) -> tuple[int, str]:
    prompt = build_implementation_prompt(task, state, failure)
    return command_with_output(
        [
            legacy.sys.executable,
            "scripts/pasi_chat_guard.py",
            prompt,
            "--github",
            "public",
            "--timeout",
            str(TASK_TIMEOUT_SECONDS),
        ],
        Path(state.worktree),
        timeout=TASK_TIMEOUT_SECONDS + 45.0,
    )


def invoke_gate(state: OvernightState) -> tuple[int, str]:
    return command_with_output(
        [
            legacy.sys.executable,
            "scripts/pasi_chat_guard.py",
            build_gate_prompt(state),
            "--github",
            "public",
            "--timeout",
            str(TASK_TIMEOUT_SECONDS),
        ],
        Path(state.worktree),
        timeout=TASK_TIMEOUT_SECONDS + 45.0,
    )


def provider_condition(code: int, output: str) -> str | None:
    upper = output.upper()
    if code == 90 or "CHAT_USAGE_LIMITED:" in upper:
        return "provider_usage_limit"
    if code == 91 or "CHAT_AUTH_REQUIRED:" in upper:
        return "auth_required"
    if code == 92 or "CHAT_GUARD_TIMEOUT:" in upper or "BROWSER CONTROLLER IS NOT REPORTING" in upper:
        return "runtime_guard"
    return None


def runtime_watchdog_is_live(*, max_age_seconds: float = WATCHDOG_MAX_AGE_SECONDS) -> bool:
    try:
        with urllib.request.urlopen(f"{BRIDGE_URL}/browser/observation", timeout=3.0) as response:
            payload = json.loads(response.read(2_000_000).decode("utf-8"))
    except (OSError, urllib.error.URLError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    observation = payload.get("observation") if isinstance(payload, dict) else None
    if not isinstance(observation, dict) or observation.get("kind") != "chatgpt_health":
        return False
    captured_at = observation.get("captured_at")
    if not isinstance(captured_at, str):
        return False
    try:
        timestamp = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    age = (now_utc() - timestamp).total_seconds()
    return -5.0 <= age <= max_age_seconds


def sleep_with_deadline(seconds: float, state: OvernightState) -> bool:
    if seconds <= 0:
        return True
    deadline = datetime.fromisoformat(state.deadline_at)
    end = min(now_utc() + timedelta(seconds=seconds), deadline)
    while not STOP and now_utc() < end:
        time.sleep(min(1.0, max(0.0, (end - now_utc()).total_seconds())))
    return not STOP and now_utc() < deadline


def verify_and_commit(worktree: Path, branch: str, task: str, patch: str, allow_delete: bool, *, push: bool) -> tuple[str, str]:
    validate_patch_paths(patch, allow_delete)
    code, output = command_with_output(["git", "apply", "--check", "--whitespace=nowarn"], worktree, 60.0)
    if code != 0:
        raise OvernightV2Error(f"git apply --check failed:\n{output}")
    code, output = command_with_output(["git", "apply", "--whitespace=nowarn"], worktree, 60.0)
    if code != 0:
        raise OvernightV2Error(f"git apply failed:\n{output}")
    code, output = command_with_output(["bash", "scripts/check_all.sh"], worktree, 900.0)
    if code != 0:
        raise OvernightV2Error(f"canonical validation failed:\n{output}")
    code, status = command_with_output(["git", "status", "--porcelain"], worktree, 30.0)
    if code != 0 or not status:
        raise OvernightV2Error("verification passed but no repository changes remain")
    commit = legacy.commit_and_push(worktree, branch, task, push)
    return commit, output


def finish_state(state: OvernightState, reason: str) -> None:
    state.stop_reason = reason
    state.last_result = reason
    save_state(state)
    log_event("run_finished", phase=state.phase, completed_tasks=state.completed_tasks, failed_tasks=state.failed_tasks, provider_limit_pauses=state.provider_limit_pauses, reason=reason)


def run(state: OvernightState, *, push: bool) -> None:
    failure = ""
    runtime_backoff = 5.0
    while not STOP and now_utc() < datetime.fromisoformat(state.deadline_at):
        if state.phase == "automation" and state.automation_tasks_since_gate >= AUTOMATION_TASKS_PER_GATE:
            state.task_number += 1
            state.current_attempt = 1
            save_state(state)
            log_event("automation_gate_started", task_number=state.task_number, completed_tasks=state.completed_tasks)
            code, response = invoke_gate(state)
            condition = provider_condition(code, response)
            if condition == "provider_usage_limit":
                state.provider_limit_pauses += 1
                log_event("provider_usage_limit", task_number=state.task_number, pause_count=state.provider_limit_pauses, context="automation_gate")
                if state.provider_limit_pauses > MAX_PROVIDER_LIMIT_PAUSES:
                    state.stop_reason = "ChatGPT provider/account/model usage limit persisted beyond bounded recovery budget; human intervention is required."
                    return
                state.task_number -= 1
                if not sleep_with_deadline(PROVIDER_BACKOFF_SECONDS[state.provider_limit_pauses - 1], state):
                    return
                continue
            if condition == "auth_required":
                state.stop_reason = "ChatGPT requires interactive authentication or a security challenge; unattended execution cannot proceed."
                save_state(state)
                return
            if condition == "runtime_guard":
                failure = response or "runtime guard stopped the automation gate"
                state.task_number -= 1
                if not sleep_with_deadline(runtime_backoff, state):
                    return
                runtime_backoff = min(runtime_backoff * 2.0, MAX_CONTROLLER_BACKOFF)
                continue
            if code != 0:
                failure = response or "automation gate invocation failed"
                log_event("automation_gate_failed", error=failure[-6000:])
                state.task_number -= 1
                if not sleep_with_deadline(runtime_backoff, state):
                    return
                runtime_backoff = min(runtime_backoff * 2.0, MAX_CONTROLLER_BACKOFF)
                continue
            status, summary, suggested, _patch, _allow_delete, values = parse_v2_response(response)
            if status != "complete" or not legacy.completion_contract_is_satisfied(status, values) or not automation_gate_is_satisfied(values):
                failure = summary or "automation gate lacked a valid evidence-backed transition"
                log_event("automation_gate_rejected", error=failure, values=values)
                state.task_number -= 1
                continue
            state.automation_gates += 1
            if values["automation_gate"] == "proceed_engineering" and values["automation_opportunity"] == "none":
                state.phase = "engineering_os"
                state.automation_tasks_since_gate = 0
                state.current_task = state.requested_task or choose_unique(ENGINEERING_TASKS, state)
                state.next_task = state.current_task
                save_state(state)
                log_event("phase_transition", from_phase="automation", to_phase="engineering_os", evidence=values.get("automation_evidence", ""))
            else:
                state.automation_tasks_since_gate = 0
                state.current_task = suggested or choose_unique(AUTOMATION_TASKS, state)
                state.next_task = state.current_task
                save_state(state)
                log_event("automation_continues", evidence=values.get("automation_evidence", ""), next_task=state.current_task)
            runtime_backoff = 5.0
            continue

        state.task_number += 1
        state.current_attempt = 0
        if not state.current_task:
            if state.phase == "automation":
                state.current_task = choose_unique(AUTOMATION_TASKS, state)
            else:
                state.current_task = state.requested_task or choose_unique(ENGINEERING_TASKS, state)
        state.recent_tasks.append(state.current_task)
        state.recent_tasks = state.recent_tasks[-12:]
        save_state(state)
        log_event("task_started", phase=state.phase, task_number=state.task_number, task=state.current_task)

        finished = False
        while state.current_attempt < MAX_ATTEMPTS and not STOP:
            if now_utc() >= datetime.fromisoformat(state.deadline_at):
                return
            state.current_attempt += 1
            save_state(state)
            code, response = invoke_chat(state.current_task, state, failure)
            condition = provider_condition(code, response)
            if condition == "provider_usage_limit":
                state.provider_limit_pauses += 1
                log_event("provider_usage_limit", task_number=state.task_number, pause_count=state.provider_limit_pauses)
                if state.provider_limit_pauses > MAX_PROVIDER_LIMIT_PAUSES:
                    state.stop_reason = "ChatGPT provider/account/model usage limit persisted beyond bounded recovery budget; human intervention is required."
                    return
                pause_seconds = PROVIDER_BACKOFF_SECONDS[state.provider_limit_pauses - 1]
                state.current_attempt -= 1
                save_state(state)
                if not sleep_with_deadline(pause_seconds, state):
                    return
                continue
            if condition == "auth_required":
                state.stop_reason = "ChatGPT requires interactive authentication or a security challenge; unattended execution cannot proceed."
                save_state(state)
                return
            if condition == "runtime_guard":
                failure = response or "runtime guard stopped the ChatGPT task"
                if not sleep_with_deadline(runtime_backoff, state):
                    return
                runtime_backoff = min(runtime_backoff * 2.0, MAX_CONTROLLER_BACKOFF)
                state.current_attempt -= 1
                continue
            if code != 0:
                failure = response or "ChatGPT invocation failed without diagnostic output"
                log_event("task_invocation_failed", task_number=state.task_number, attempt=state.current_attempt, error=failure[-6000:])
                continue

            runtime_backoff = 5.0
            status, summary, next_task, patch, allow_delete, values = parse_v2_response(response)
            contract_ok = legacy.completion_contract_is_satisfied(status, values)
            log_event("task_response", phase=state.phase, task_number=state.task_number, attempt=state.current_attempt, status=status, contract_ok=contract_ok, summary=summary, evidence=values)
            if not patch or not contract_ok:
                failure = summary or "completion contract not satisfied or implementation patch missing"
                continue
            try:
                commit, verification = verify_and_commit(Path(state.worktree), state.branch, state.current_task, patch, allow_delete, push=push)
            except Exception as exc:
                failure = str(exc)
                log_event("task_verification_failed", task_number=state.task_number, attempt=state.current_attempt, error=failure[-6000:])
                command_with_output(["git", "reset", "--hard", "HEAD"], Path(state.worktree), 60.0)
                command_with_output(["git", "clean", "-fd"], Path(state.worktree), 60.0)
                continue

            state.completed_tasks += 1
            if state.phase == "automation":
                state.automation_tasks_since_gate += 1
            state.provider_limit_pauses = 0
            state.last_result = summary or values.get("evidence", "validated task completed")
            state.next_task = next_task.strip() if next_task.strip() else ""
            state.current_attempt = 0
            state.current_task = ""
            save_state(state)
            log_event("task_completed", phase=state.phase, task_number=state.task_number, commit=commit, verification=verification[-4000:], next_task=state.next_task)
            finished = True
            failure = ""
            break

        if not finished:
            state.failed_tasks += 1
            state.last_result = failure or "task exceeded bounded retry budget"
            state.current_task = (
                "Recover the blocked PASI task by diagnosing its verified failure and implementing a different concrete workaround without repeating the unsuccessful approach."
                if state.phase == "automation"
                else "Recover the blocked Engineering OS task using verified repository evidence and a materially different concrete approach."
            )
            state.next_task = ""
            save_state(state)
            log_event("task_failed", phase=state.phase, task_number=state.task_number, error=state.last_result[-6000:])
            command_with_output(["git", "reset", "--hard", "HEAD"], Path(state.worktree), 60.0)
            command_with_output(["git", "clean", "-fd"], Path(state.worktree), 60.0)
            continue

        if state.next_task:
            state.current_task = state.next_task
        elif state.phase == "automation":
            state.current_task = choose_unique(AUTOMATION_TASKS, state)
        else:
            state.current_task = choose_unique(ENGINEERING_TASKS, state)
        save_state(state)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run PASI unattended with provider-aware recovery and an evidence-gated Engineering OS transition.")
    parser.add_argument("--hours", type=float, default=DEFAULT_HOURS)
    parser.add_argument("--task", default="")
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
    children: list[Any] = []
    try:
        code, output = command_with_output(["git", "fetch", "origin", "main"], REPO_ROOT, 120.0)
        if code != 0:
            raise OvernightV2Error(f"git fetch origin main failed: {output}")

        saved = load_state() if args.resume else None
        if saved is not None and now_utc() < datetime.fromisoformat(saved.deadline_at):
            state = saved
            resume = True
            log_event("run_resumed", **state.to_dict())
        else:
            started = now_utc()
            state = OvernightState(
                schema_version=2,
                run_id=f"overnight-{uuid.uuid4().hex}",
                started_at=started.isoformat(),
                deadline_at=(started + timedelta(hours=args.hours)).isoformat(),
                worktree=str(args.worktree.expanduser().resolve()),
                branch=args.branch,
                phase="automation",
                current_task=AUTOMATION_TASKS[0],
                requested_task=args.task.strip(),
            )
            resume = False
            save_state(state)
            log_event("run_started", **state.to_dict(), push=not args.no_push)

        legacy.ensure_worktree(Path(state.worktree), state.branch, resume=resume)
        children = legacy.ensure_services()
        if not runtime_watchdog_is_live():
            raise OvernightV2Error(
                "ChatGPT runtime watchdog is not reporting fresh health telemetry. Install and enable "
                "automation/tampermonkey/chatgpt-runtime-watchdog.user.js, open chatgpt.com, and refresh before starting unattended automation."
            )
        run(state, push=not args.no_push)
        reason = state.stop_reason or ("stopped by operator" if STOP else "overnight deadline reached")
        finish_state(state, reason)
        return 0
    except Exception as exc:
        log_event("run_failed", error=str(exc))
        return 1
    finally:
        release_lock()
        for child in children:
            try:
                if child.poll() is None:
                    child.terminate()
            except Exception:
                pass
        for child in children:
            try:
                child.wait(timeout=5)
            except Exception:
                try:
                    child.kill()
                except Exception:
                    pass


if __name__ == "__main__":
    raise SystemExit(main())
