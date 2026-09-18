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
from typing import Any, Mapping, Sequence

from scripts import pasi_overnight_engine as legacy

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = REPO_ROOT / ".runtime" / "overnight"
STATE_PATH = RUNTIME_DIR / "state.json"
EVENT_LOG = RUNTIME_DIR / "events.jsonl"
PID_PATH = RUNTIME_DIR / "runner.pid"
BRIDGE_URL = "http://127.0.0.1:8765"
DEFAULT_WORKTREE = legacy.DEFAULT_WORKTREE
DEFAULT_HOURS = legacy.DEFAULT_HOURS
MIN_HOURS = legacy.MIN_HOURS
MAX_HOURS = legacy.MAX_HOURS
MAX_ATTEMPTS = legacy.MAX_ATTEMPTS
TASK_TIMEOUT_SECONDS = 900.0
WATCHDOG_MAX_AGE_SECONDS = 30.0
STANDBY_SECONDS = 30.0
AUTOMATION_TASKS_PER_GATE = 2
MAX_PROVIDER_LIMIT_PAUSES = 3

AUTOMATION_TASKS = (
    "Audit the PASI computer-use control plane end to end and implement concrete changes that reduce repeated human input, improve state continuity, improve browser recovery, and preserve all existing safety boundaries.",
    "Harden PASI unattended operation against transient ChatGPT/controller failures: improve bounded retries, response detection, context rollover handling, diagnostics, and recovery without weakening human approval boundaries.",
    "Improve PASI browser automation by reducing dependency on Tampermonkey, strengthening refresh/recovery behavior, and preserving provider-specific ChatGPT behavior behind a clean capability boundary.",
)
ENGINEERING_TASKS = (
    "Improve engineering evidence and verification so completion is based on reproducible tests, diagnostics, repository state, and concrete evidence instead of model claims.",
    "Improve PASI task continuation so verified repository gaps deterministically produce useful next tasks without unnecessary repetition.",
    "Improve provider-neutral engineering adapters and control-plane boundaries so PASI can support additional AI providers without weakening authorization or verification.",
    "Improve website and application verification so functionality, completeness, performance, accessibility, and obvious integration failures are tested rather than inferred.",
)

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
    requested_task: str = ""
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
    temporary = STATE_PATH.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(state.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(STATE_PATH)


def load_state() -> OvernightState | None:
    try:
        raw = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict) or int(raw.get("schema_version", 0)) != 2:
        return None
    try:
        phase = str(raw["phase"])
        if phase not in {"automation", "engineering_os"}:
            return None
        recent = raw.get("recent_tasks", [])
        recent_tasks = [str(item) for item in recent if isinstance(item, str)] if isinstance(recent, list) else []
        return OvernightState(
            schema_version=2,
            run_id=str(raw["run_id"]),
            started_at=str(raw["started_at"]),
            deadline_at=str(raw["deadline_at"]),
            worktree=str(raw["worktree"]),
            branch=str(raw["branch"]),
            phase=phase,
            current_task=str(raw["current_task"]),
            requested_task=str(raw.get("requested_task", "")),
            task_number=int(raw.get("task_number", 0)),
            completed_tasks=int(raw.get("completed_tasks", 0)),
            failed_tasks=int(raw.get("failed_tasks", 0)),
            current_attempt=int(raw.get("current_attempt", 0)),
            automation_tasks_since_gate=int(raw.get("automation_tasks_since_gate", 0)),
            automation_gates=int(raw.get("automation_gates", 0)),
            provider_limit_pauses=int(raw.get("provider_limit_pauses", 0)),
            last_result=str(raw.get("last_result", "")),
            next_task=str(raw.get("next_task", "")),
            stop_reason=str(raw.get("stop_reason", "")),
            recent_tasks=recent_tasks[-12:],
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
                raise RuntimeError(f"another overnight runner may be active (PID {pid})") from exc
            except OSError:
                pass
            else:
                raise RuntimeError(f"another overnight runner is already active (PID {pid})")
    PID_PATH.write_text(f"{os.getpid()}\n", encoding="utf-8")


def release_lock() -> None:
    try:
        PID_PATH.unlink()
    except FileNotFoundError:
        pass


def validate_patch_paths(patch: str, allow_delete: bool) -> None:
    legacy.validate_patch_paths(patch, allow_delete)


def command(command: list[str], cwd: Path, timeout: float) -> tuple[int, str]:
    try:
        result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)
    output = ((result.stdout or "") + (result.stderr or "")).strip()
    return result.returncode, output[-20_000:]


def healthy(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=3.0) as response:
            return 200 <= response.status < 300
    except (OSError, urllib.error.URLError):
        return False


def ensure_services() -> list[subprocess.Popen[bytes]]:
    children: list[subprocess.Popen[bytes]] = []
    if not healthy(f"{BRIDGE_URL}/health"):
        log_event("service_start", service="bridge")
        children.append(subprocess.Popen([legacy.sys.executable, "-m", "automation.orchestrator.bridge"], cwd=REPO_ROOT))
    if not healthy("http://127.0.0.1:8766/health"):
        log_event("service_start", service="controller_distribution")
        children.append(subprocess.Popen([legacy.sys.executable, "scripts/pasi_controller_server.py"], cwd=REPO_ROOT))
    deadline = time.monotonic() + 20.0
    while time.monotonic() < deadline:
        if healthy(f"{BRIDGE_URL}/health") and healthy("http://127.0.0.1:8766/health"):
            return children
        time.sleep(0.5)
    raise RuntimeError("local PASI bridge/distribution services did not become healthy")


def ensure_worktree(path: Path, branch: str, *, resume: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not (path / ".git").exists():
        code, output = command(["git", "worktree", "add", "-B", branch, str(path), "origin/main"], REPO_ROOT, 60.0)
        if code != 0:
            raise RuntimeError(f"could not create overnight worktree: {output}")
        return
    code, output = command(["git", "status", "--porcelain"], path, 15.0)
    if code != 0:
        raise RuntimeError(f"could not inspect overnight worktree: {output}")
    if output and not resume:
        raise RuntimeError("overnight worktree contains local changes")
    if output:
        log_event("resume_cleanup", reason="discarding interrupted-task changes in dedicated overnight worktree")
        for cleanup in (["git", "reset", "--hard", "HEAD"], ["git", "clean", "-fd"]):
            cleanup_code, cleanup_output = command(cleanup, path, 60.0)
            if cleanup_code != 0:
                raise RuntimeError(f"could not recover overnight worktree: {cleanup_output}")
    code, output = command(["git", "checkout", branch], path, 30.0)
    if code != 0:
        raise RuntimeError(f"could not select overnight branch: {output}")

    code, counts = command(["git", "rev-list", "--left-right", "--count", f"{branch}...origin/main"], path, 30.0)
    if code != 0:
        raise RuntimeError(f"could not compare overnight branch with origin/main: {counts}")
    parts = counts.split()
    if len(parts) != 2:
        raise RuntimeError(f"could not parse overnight branch ancestry: {counts}")
    try:
        ahead, behind = int(parts[0]), int(parts[1])
    except ValueError as exc:
        raise RuntimeError(f"could not parse overnight branch ancestry: {counts}") from exc
    if behind > 0 and ahead == 0:
        merge_code, merge_output = command(["git", "merge", "--ff-only", "origin/main"], path, 60.0)
        if merge_code != 0:
            raise RuntimeError(f"could not fast-forward overnight branch to origin/main: {merge_output}")
        log_event("resume_branch_fast_forwarded", branch=branch, commits=behind)
    elif behind > 0 and ahead > 0:
        log_event("resume_branch_diverged", branch=branch, ahead=ahead, behind=behind)


def browser_observation() -> dict[str, Any] | None:
    try:
        with urllib.request.urlopen(f"{BRIDGE_URL}/browser/observation", timeout=3.0) as response:
            payload = json.loads(response.read(2_000_000).decode("utf-8"))
    except (OSError, urllib.error.URLError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    observation = payload.get("observation") if isinstance(payload, dict) else None
    return observation if isinstance(observation, dict) else None


def _observation_time(observation: dict[str, Any]) -> datetime | None:
    captured_at = observation.get("captured_at")
    if not isinstance(captured_at, str):
        return None
    try:
        value = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def runtime_watchdog_is_live(*, max_age_seconds: float = WATCHDOG_MAX_AGE_SECONDS) -> bool:
    observation = browser_observation()
    if observation is None:
        return False
    kind = observation.get("kind")
    if kind not in {"chatgpt_health", "chatgpt_state"}:
        return False
    timestamp = _observation_time(observation)
    if timestamp is None:
        return False
    age = (now_utc() - timestamp).total_seconds()
    return -5.0 <= age <= max_age_seconds


def provider_condition(code: int, output: str) -> str | None:
    upper = output.upper()
    if code == 90 or "CHAT_USAGE_LIMITED:" in upper:
        return "provider_usage_limit"
    if code == 91 or "CHAT_AUTH_REQUIRED:" in upper:
        return "auth_required"
    if code == 92 or "CHAT_GUARD_TIMEOUT:" in upper or "BROWSER CONTROLLER IS NOT REPORTING" in upper:
        return "runtime_guard"
    return None


def automation_gate_is_satisfied(evidence: Mapping[str, object]) -> bool:
    gate = evidence.get("automation_gate")
    opportunity = evidence.get("automation_opportunity")
    evidence_text = evidence.get("automation_evidence")
    if not isinstance(gate, str) or not isinstance(opportunity, str) or not isinstance(evidence_text, str) or not evidence_text.strip():
        return False
    if gate == "proceed_engineering":
        return opportunity == "none"
    if gate == "continue_automation":
        return opportunity == "concrete"
    return False


def choose_unique(candidates: Sequence[str], state: OvernightState) -> str:
    values = tuple(str(item).strip() for item in candidates if str(item).strip())
    if not values:
        raise RuntimeError("no candidate tasks are configured")
    recent = {item.casefold() for item in state.recent_tasks[-12:]}
    for candidate in values:
        if candidate.casefold() not in recent:
            return candidate
    return values[state.completed_tasks % len(values)]


def invoke_chat(task: str, state: OvernightState, failure: str) -> tuple[int, str]:
    prompt = build_prompt(task, state, failure)
    code, output = command(
        [legacy.sys.executable, "scripts/pasi_chat_guard.py", prompt, "--github", "public", "--timeout", str(TASK_TIMEOUT_SECONDS)],
        Path(state.worktree),
        TASK_TIMEOUT_SECONDS + 45.0,
    )
    if provider_condition(code, output) is None:
        return code, output
    fallback = command(
        [legacy.sys.executable, "scripts/pasi_provider_router.py", "--task", prompt, "--repo", str(state.worktree), "--timeout", "180"],
        Path(state.worktree),
        225.0,
    )
    if fallback[0] == 0 and fallback[1].strip():
        return 0, fallback[1]
    return code, output + "\n\n[PASI FALLBACK ROUTER]\n" + fallback[1]


def parse_response(response: str) -> tuple[str, str, str, str, bool, dict[str, str]]:
    return legacy.parse_response(response)


def completion_contract(status: str, values: dict[str, str]) -> bool:
    return legacy.completion_contract_is_satisfied(status, values)


def continuation_directive(state: OvernightState, task: str) -> str:
    candidates = AUTOMATION_TASKS if state.phase == "automation" else ENGINEERING_TASKS
    roadmap = "\n".join(f"- {item}" for item in candidates)
    recent = "\n".join(f"- {item}" for item in state.recent_tasks[-12:]) or "- none recorded"
    return f"""TASK CONTINUATION / ANTI-LOOP POLICY:
- First inspect the current repository state and recent commits before deciding whether the CURRENT TASK is still incomplete.
- IF the CURRENT TASK is already satisfied by verified repository changes and evidence, THEN do not re-implement it, do not make cosmetic duplicate changes, and do not ask the human what to do next; immediately work on the next incomplete roadmap item below.
- IF the CURRENT TASK is not yet satisfied, THEN continue it and use a materially different approach when PREVIOUS FAILURE EVIDENCE shows the prior approach failed.
- A response-repair prompt repairs the response contract; it does not restart an implementation that is already verified.
- After a verified completion, set PASI_RESULT_NEXT_TASK to the next incomplete, high-value item rather than repeating CURRENT TASK.
- IF the listed roadmap items are already covered by verified recent work, THEN revisit the repository for the next concrete gap and make that the next task instead of repeating an old task.
- After any successful completion or bounded failure, continue automatically to the next incomplete roadmap task until the run deadline or an explicit operator stop; do not terminate merely because one task or one provider path finished.
ROADMAP PHASE: {state.phase}
ROADMAP:
{roadmap}
RECENT TASKS:
{recent}

CURRENT TASK:
{task}"""

def build_prompt(task: str, state: OvernightState, failure: str = "") -> str:
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
- Canonical public repository: https://github.com/th3-st0v3/personal-ai-system
- Thinking is required for every ChatGPT task.
- Public GitHub repository is the default context source.
- OpenRouter, Perplexity, OpenCode, and direct HTTPS research are permitted fallback evidence/model sources when ChatGPT is unavailable.

{continuation_directive(state, task)}

AUTOMATION OBJECTIVE:
Keep progressing without getting trapped by a dead ChatGPT tab, transient provider limit, stale controller, repeated failed approach, or unavailable optional provider. Stand by and retry boundedly when recovery is possible; change strategy when the same failure repeats.

COMPLETION CONTRACT:
Do not mark complete until the stated requirement is implemented and reproducible evidence supports it. Never claim files changed or tests passed without evidence.

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


def choose_next_task(state: OvernightState, suggested: str) -> str:
    candidate = re.sub(r"\s+", " ", suggested).strip()
    candidates = AUTOMATION_TASKS if state.phase == "automation" else ENGINEERING_TASKS
    configured = {item.casefold(): item for item in candidates}
    recent = {item.casefold() for item in state.recent_tasks[-12:]}
    if candidate.casefold() in configured and candidate.casefold() not in recent:
        return configured[candidate.casefold()]
    return choose_unique(candidates, state)


def verify_and_commit(worktree: Path, branch: str, task: str, patch: str, allow_delete: bool, *, push: bool) -> tuple[str, str]:
    validate_patch_paths(patch, allow_delete)
    code, output = command(["git", "apply", "--check", "--whitespace=nowarn"], worktree, 60.0)
    if code != 0:
        raise RuntimeError(f"git apply --check failed:\n{output}")
    code, output = command(["git", "apply", "--whitespace=nowarn"], worktree, 60.0)
    if code != 0:
        raise RuntimeError(f"git apply failed:\n{output}")
    code, output = command(["bash", "scripts/check_all.sh"], worktree, 900.0)
    if code != 0:
        raise RuntimeError(f"canonical validation failed:\n{output}")
    code, status = command(["git", "status", "--porcelain"], worktree, 30.0)
    if code != 0 or not status:
        raise RuntimeError("verification passed but no repository changes remain")
    commit = legacy.commit_and_push(worktree, branch, task, push)
    if push:
        promotion = command(
            [
                legacy.sys.executable,
                "scripts/pasi_promote.py",
                "--commit",
                commit,
                "--branch",
                branch,
                "--task",
                task,
                "--json",
            ],
            worktree,
            90.0,
        )
        if promotion[0] == 0:
            output = output + "\n\n[PASI PROMOTION]\n" + promotion[1]
        else:
            log_event("promotion_deferred", commit=commit, branch=branch, error=promotion[1][-4000:])
            output = output + "\n\n[PASI PROMOTION DEFERRED]\n" + promotion[1][-4000:]
    return commit, output


def standby_until_ready(state: OvernightState) -> bool:
    logged = False
    while not STOP and now_utc() < datetime.fromisoformat(state.deadline_at):
        observation = browser_observation()
        if observation:
            data = observation.get("data") if isinstance(observation.get("data"), dict) else observation
            if isinstance(data, dict) and bool(data.get("auth_required")):
                log_event("standby_auth_required")
                return False
        if runtime_watchdog_is_live():
            if logged:
                log_event("standby_recovered")
            return True
        if not logged:
            log_event("standby_started", reason="browser controller/extension heartbeat is stale; waiting for recovery")
            logged = True
        remaining = (datetime.fromisoformat(state.deadline_at) - now_utc()).total_seconds()
        time.sleep(min(STANDBY_SECONDS, max(1.0, remaining)))
    return False


def on_signal(signum: int, _frame: object) -> None:
    global STOP
    STOP = True
    log_event("stop_requested", signal=signum)


def sleep_until_retry(state: OvernightState, seconds: float) -> bool:
    deadline = datetime.fromisoformat(state.deadline_at)
    end = min(deadline, now_utc() + timedelta(seconds=max(0.0, seconds)))
    while not STOP and now_utc() < end:
        time.sleep(min(1.0, max(0.1, (end - now_utc()).total_seconds())))
    return not STOP and now_utc() < deadline


def run(state: OvernightState, *, push: bool) -> None:
    failure = ""
    while not STOP and now_utc() < datetime.fromisoformat(state.deadline_at):
        if not runtime_watchdog_is_live():
            if not standby_until_ready(state):
                if STOP:
                    return
                state.stop_reason = "ChatGPT/browser runtime did not recover before the overnight deadline."
                save_state(state)
                return

        if state.phase == "automation" and state.automation_tasks_since_gate >= AUTOMATION_TASKS_PER_GATE:
            gate_evidence = {
                "automation_gate": "proceed_engineering",
                "automation_opportunity": "none",
                "automation_evidence": "The bounded automation tranche has completed its configured tasks; future improvements remain available as ordinary engineering tasks.",
            }
            if automation_gate_is_satisfied(gate_evidence):
                state.automation_gates += 1
                state.automation_tasks_since_gate = 0
                save_state(state)
                log_event("automation_gate", gate=state.automation_gates, action="proceed_to_engineering_os")
                state.phase = "engineering_os"
                state.current_task = ENGINEERING_TASKS[0]
                save_state(state)
                continue

        state.task_number += 1
        state.current_attempt = 0
        save_state(state)
        finished = False
        for attempt in range(1, MAX_ATTEMPTS + 1):
            if STOP or now_utc() >= datetime.fromisoformat(state.deadline_at):
                return
            state.current_attempt = attempt
            save_state(state)
            log_event("task_attempt_started", phase=state.phase, task_number=state.task_number, attempt=attempt, task=state.current_task)
            code, response = invoke_chat(state.current_task, state, failure)
            condition = provider_condition(code, response)
            if condition == "auth_required":
                log_event("fallback_provider_route", reason="ChatGPT authentication challenge", task_number=state.task_number)
                fallback = command([legacy.sys.executable, "scripts/pasi_provider_router.py", "--task", build_prompt(state.current_task, state, response), "--repo", state.worktree, "--timeout", "180"], Path(state.worktree), 225.0)
                if fallback[0] == 0:
                    response = fallback[1]
                    code = 0
            elif condition in {"provider_usage_limit", "runtime_guard"}:
                if condition == "provider_usage_limit":
                    state.provider_limit_pauses += 1
                    if state.provider_limit_pauses > MAX_PROVIDER_LIMIT_PAUSES:
                        failure = response[-12_000:] or "provider usage limit persisted across bounded pauses"
                        log_event("provider_pause_budget_exhausted", task_number=state.task_number, count=state.provider_limit_pauses)
                        break
                log_event("provider_pause", condition=condition, count=state.provider_limit_pauses)
                if not sleep_until_retry(state, 30.0 if condition == "runtime_guard" else 300.0):
                    return
                failure = response[-12_000:]
                continue

            if code != 0:
                failure = response[-12_000:] or "ChatGPT fallback returned a non-zero exit status"
                continue
            status, summary, next_task, patch, allow_delete, values = parse_response(response)
            if not completion_contract(status, values) or not patch:
                failure = summary or response[-12_000:] or "provider returned no usable completion contract"
                continue
            try:
                commit, verification = verify_and_commit(Path(state.worktree), state.branch, state.current_task, patch, allow_delete, push=push)
            except Exception as exc:
                failure = str(exc)
                log_event("verification_failed", task_number=state.task_number, attempt=attempt, error=failure[-6000:])
                command(["git", "reset", "--hard", "HEAD"], Path(state.worktree), 60.0)
                command(["git", "clean", "-fd"], Path(state.worktree), 60.0)
                continue
            state.completed_tasks += 1
            if state.phase == "automation":
                state.automation_tasks_since_gate += 1
            state.last_result = summary or verification[-3000:]
            state.next_task = next_task.strip()
            state.recent_tasks.append(state.current_task)
            state.current_task = choose_next_task(state, state.next_task)
            state.next_task = ""
            state.current_attempt = 0
            save_state(state)
            log_event("task_completed", phase=state.phase, task_number=state.task_number, commit=commit, summary=summary[-2000:])
            failure = ""
            finished = True
            break
        if not finished:
            failed_task = state.current_task
            state.failed_tasks += 1
            state.last_result = failure or "bounded retry budget exhausted"
            state.recent_tasks.append(failed_task)
            state.recent_tasks = state.recent_tasks[-12:]
            state.current_task = choose_next_task(state, "")
            save_state(state)
            log_event("task_failed", phase=state.phase, task_number=state.task_number, failed_task=failed_task, next_task=state.current_task, error=state.last_result[-6000:])
            failure = state.last_result


def finish_state(state: OvernightState, reason: str) -> None:
    state.stop_reason = reason
    state.last_result = reason
    save_state(state)
    log_event("run_finished", phase=state.phase, completed_tasks=state.completed_tasks, failed_tasks=state.failed_tasks, provider_limit_pauses=state.provider_limit_pauses, reason=reason)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run PASI unattended with bounded recovery and provider fallback.")
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
    children: list[subprocess.Popen[bytes]] = []
    state: OvernightState | None = None
    try:
        code, output = command(["git", "fetch", "origin", "main"], REPO_ROOT, 120.0)
        if code != 0:
            raise RuntimeError(f"git fetch origin main failed: {output}")
        saved = load_state() if args.resume else None
        if saved is not None and now_utc() < datetime.fromisoformat(saved.deadline_at):
            state = saved
            state.stop_reason = ""
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
                current_task=args.task.strip() or AUTOMATION_TASKS[0],
                requested_task=args.task.strip(),
            )
            resume = False
            save_state(state)
            log_event("run_started", **state.to_dict(), push=not args.no_push)

        ensure_worktree(Path(state.worktree), state.branch, resume=resume)
        children = ensure_services()
        run(state, push=not args.no_push)
        if not state.stop_reason:
            finish_state(state, "deadline_reached" if now_utc() >= datetime.fromisoformat(state.deadline_at) else "stopped")
        return 0
    except KeyboardInterrupt:
        if state is not None:
            finish_state(state, "keyboard_interrupt")
        return 130
    except Exception as exc:
        if state is not None:
            state.stop_reason = str(exc)
            save_state(state)
            log_event("run_failed", error=str(exc))
        return 1
    finally:
        STOP = True
        for child in children:
            try:
                child.terminate()
            except Exception:
                pass
        release_lock()


if __name__ == "__main__":
    raise SystemExit(main())
