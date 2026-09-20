from __future__ import annotations

import argparse
import hashlib
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
from scripts import pasi_prompt_compiler as prompt_compiler

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = REPO_ROOT / ".runtime" / "overnight"
STATE_PATH = RUNTIME_DIR / "state.json"
EVENT_LOG = RUNTIME_DIR / "events.jsonl"
PID_PATH = RUNTIME_DIR / "runner.pid"
ROADMAP_LOOP_GUARD_PATH = RUNTIME_DIR / "roadmap-loop-guard.json"
BRIDGE_URL = "http://127.0.0.1:8765"
CONTROLLER_MANIFEST_PATH = REPO_ROOT / "automation" / "tampermonkey" / "controller-sync.json"
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
AUTH_RECOVERY_WAIT_SECONDS = 300.0
AUTH_RECOVERY_POLL_SECONDS = 5.0
FALLBACK_ROUTER_COOLDOWN_SECONDS = 900.0
ROADMAP_CONSECUTIVE_RUN_LIMIT = 2
ROADMAP_LOOP_GUARD_HISTORY_LIMIT = 24
TASK_LEDGER_PATH = RUNTIME_DIR / "task-ledger.json"
MAX_TASK_TEXT_CHARS = 4000
CONTROL_SCRIPTS_ROOT = REPO_ROOT / "scripts"
AUTOMATION_CONTINUE_RE = re.compile(r"^PASI_AUTOMATION_CONTINUE:\s*true$", re.MULTILINE | re.IGNORECASE)

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
    fallback_router_disabled_until: str = ""
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
            "fallback_router_disabled_until": self.fallback_router_disabled_until,
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
            fallback_router_disabled_until=str(raw.get("fallback_router_disabled_until", "")),
            last_result=str(raw.get("last_result", "")),
            next_task=str(raw.get("next_task", "")),
            stop_reason=str(raw.get("stop_reason", "")),
            recent_tasks=recent_tasks[-12:],
        )
    except (KeyError, TypeError, ValueError):
        return None



def task_key(task: str) -> str:
    canonical = re.sub(r"\s+", " ", task).strip()[:MAX_TASK_TEXT_CHARS]
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_task_ledger() -> dict[str, dict[str, Any]]:
    try:
        raw = json.loads(TASK_LEDGER_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    entries = raw.get("tasks", {})
    if not isinstance(entries, dict):
        return {}
    return {str(key): dict(value) for key, value in entries.items() if isinstance(value, dict)}


def save_task_ledger(ledger: Mapping[str, Mapping[str, Any]]) -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": 1, "tasks": {str(key): dict(value) for key, value in ledger.items()}}
    temporary = TASK_LEDGER_PATH.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(TASK_LEDGER_PATH)


def record_task_ledger(
    task: str,
    status: str,
    *,
    commit: str | None = None,
    evidence: str = "",
    phase: str = "",
    automation_continue: bool = False,
) -> None:
    normalized = re.sub(r"\s+", " ", task).strip()[:MAX_TASK_TEXT_CHARS]
    if not normalized:
        return
    ledger = load_task_ledger()
    ledger[task_key(normalized)] = {
        "task": normalized,
        "status": status,
        "commit": commit or "",
        "evidence": evidence[-4000:],
        "phase": phase,
        "automation_continue": automation_continue,
        "updated_at": now_utc().isoformat(),
    }
    save_task_ledger(ledger)


def load_roadmap_selection_history() -> list[dict[str, str]]:
    try:
        raw = json.loads(ROADMAP_LOOP_GUARD_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(raw, dict) or int(raw.get("schema_version", 0)) != 1:
        return []
    selections = raw.get("selections", [])
    if not isinstance(selections, list):
        return []
    history: list[dict[str, str]] = []
    for item in selections[-ROADMAP_LOOP_GUARD_HISTORY_LIMIT:]:
        if not isinstance(item, dict):
            continue
        phase = item.get("phase")
        task = item.get("task")
        run_id = item.get("run_id")
        timestamp = item.get("timestamp")
        if not isinstance(phase, str) or not isinstance(task, str):
            continue
        if not isinstance(run_id, str) or not isinstance(timestamp, str):
            continue
        phase_text = phase.strip()
        task_text = task.strip()
        run_id_text = run_id.strip()
        timestamp_text = timestamp.strip()
        if not all((phase_text, task_text, run_id_text, timestamp_text)):
            continue
        history.append({
            "phase": phase_text,
            "task": task_text,
            "run_id": run_id_text,
            "timestamp": timestamp_text,
        })
    return history


def save_roadmap_selection_history(history: Sequence[Mapping[str, str]]) -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "selections": [dict(item) for item in history[-ROADMAP_LOOP_GUARD_HISTORY_LIMIT:]],
    }
    temporary = ROADMAP_LOOP_GUARD_PATH.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(ROADMAP_LOOP_GUARD_PATH)


def consecutive_roadmap_selection_count(
    history: Sequence[Mapping[str, str]], phase: str, task: str
) -> int:
    target_phase = phase.casefold().strip()
    target_task = task.casefold().strip()
    count = 0
    for item in reversed(history):
        if str(item.get("phase", "")).casefold().strip() != target_phase:
            break
        if str(item.get("task", "")).casefold().strip() != target_task:
            break
        count += 1
    return count


def choose_run_start_task(phase: str, requested_task: str, run_id: str) -> tuple[str, bool, int]:
    candidates = AUTOMATION_TASKS if phase == "automation" else ENGINEERING_TASKS
    candidate = re.sub(r"\s+", " ", requested_task).strip()
    configured = {item.casefold(): item for item in candidates}

    if candidate and candidate.casefold() not in configured:
        return candidate, False, 0

    candidate = configured.get(candidate.casefold(), candidates[0])
    history = load_roadmap_selection_history()
    prior_repeats = consecutive_roadmap_selection_count(history, phase, candidate)
    guard_applied = prior_repeats >= ROADMAP_CONSECUTIVE_RUN_LIMIT

    if guard_applied:
        index = next(index for index, item in enumerate(candidates) if item.casefold() == candidate.casefold())
        candidate = candidates[(index + 1) % len(candidates)]

    updated = [
        *history,
        {
            "phase": phase,
            "task": candidate,
            "run_id": run_id,
            "timestamp": now_utc().isoformat(),
        },
    ]
    save_roadmap_selection_history(updated)
    return candidate, guard_applied, prior_repeats


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


def validate_patch_paths(patch: str, allow_delete: bool, worktree: Path | None = None) -> None:
    legacy.validate_patch_paths(patch, allow_delete, worktree)


def control_script(name: str) -> Path:
    candidate = (CONTROL_SCRIPTS_ROOT / name).resolve()
    try:
        candidate.relative_to(CONTROL_SCRIPTS_ROOT.resolve())
    except ValueError as exc:
        raise ValueError(f"control script escapes launcher root: {name}") from exc
    if not candidate.is_file():
        raise FileNotFoundError(f"control script is missing from launcher checkout: {candidate}")
    return candidate


def command(
    command: list[str],
    cwd: Path,
    timeout: float,
    *,
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
    token = os.environ.get("PASI_BRIDGE_TOKEN", "").strip()
    if not token:
        try:
            token = (Path.home() / ".pasi" / "bridge-token").read_text(encoding="utf-8").strip()
        except OSError:
            return None
    request = urllib.request.Request(
        f"{BRIDGE_URL}/browser/observation",
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=3.0) as response:
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


def expected_controller_version() -> str | None:
    try:
        raw = json.loads(CONTROLLER_MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    version = raw.get("version") if isinstance(raw, dict) else None
    return version.strip() if isinstance(version, str) and version.strip() else None


def controller_observation_is_compatible(observation: dict[str, Any]) -> bool:
    data = observation.get("data") if isinstance(observation.get("data"), dict) else observation
    if not isinstance(data, dict):
        return False
    expected = expected_controller_version()
    actual = data.get("controller_version")
    return isinstance(expected, str) and expected == actual


def runtime_watchdog_is_live(*, max_age_seconds: float = WATCHDOG_MAX_AGE_SECONDS) -> bool:
    observation = browser_observation()
    if observation is None:
        return False
    data = observation.get("data") if isinstance(observation.get("data"), dict) else observation
    if not isinstance(data, dict):
        return False
    kind = data.get("kind")
    if kind not in {"chatgpt_health", "chatgpt_state"}:
        return False
    if not controller_observation_is_compatible(observation):
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

def browser_auth_required() -> bool:
    observation = browser_observation()
    if not observation:
        return False
    data = observation.get("data") if isinstance(observation.get("data"), dict) else observation
    if not isinstance(data, dict):
        return False
    return data.get("auth_required") is True or data.get("login_required") is True



def fallback_router_available(state: OvernightState) -> bool:
    value = state.fallback_router_disabled_until.strip()
    if not value:
        return True
    try:
        deadline = datetime.fromisoformat(value)
    except ValueError:
        return True
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    return now_utc() >= deadline


def disable_fallback_router(state: OvernightState, reason: str) -> None:
    state.fallback_router_disabled_until = (now_utc() + timedelta(seconds=FALLBACK_ROUTER_COOLDOWN_SECONDS)).isoformat()
    save_state(state)
    log_event(
        "fallback_router_cooldown_started",
        until=state.fallback_router_disabled_until,
        cooldown_seconds=FALLBACK_ROUTER_COOLDOWN_SECONDS,
        reason=reason[-1000:],
    )


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


def automation_gate_evidence(state: OvernightState) -> dict[str, str]:
    ledger = load_task_ledger()
    entries = [
        value
        for value in ledger.values()
        if value.get("phase") == "automation" and value.get("status") == "completed"
    ]
    entries.sort(key=lambda value: str(value.get("updated_at", "")))
    recent = entries[-AUTOMATION_TASKS_PER_GATE:]
    if len(recent) < AUTOMATION_TASKS_PER_GATE:
        return {
            "automation_gate": "continue_automation",
            "automation_opportunity": "concrete",
            "automation_evidence": "Durable task ledger does not yet contain enough completed automation tasks for a gate.",
        }
    if any(value.get("automation_continue") is True for value in recent):
        return {
            "automation_gate": "continue_automation",
            "automation_opportunity": "concrete",
            "automation_evidence": "A completed automation task explicitly requested continued automation work.",
        }
    if not all(str(value.get("evidence", "")).strip() for value in recent):
        return {
            "automation_gate": "continue_automation",
            "automation_opportunity": "concrete",
            "automation_evidence": "Recent automation task evidence is incomplete.",
        }
    return {
        "automation_gate": "proceed_engineering",
        "automation_opportunity": "none",
        "automation_evidence": "Recent automation task evidence is complete and no task explicitly requested additional automation work.",
    }


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
    log_event(
        "prompt_compiled",
        pattern_version=prompt_compiler.PROMPT_PATTERN_VERSION,
        prompt_hash=prompt_compiler.prompt_hash(prompt),
        task_key=task_key(task),
        task_number=state.task_number,
        attempt=state.current_attempt,
    )
    code, output = command(
        [legacy.sys.executable, str(control_script("pasi_chat_guard.py")), prompt, "--github", "public", "--timeout", str(TASK_TIMEOUT_SECONDS), "--repo", state.worktree],
        REPO_ROOT,
        TASK_TIMEOUT_SECONDS + 45.0,
    )
    if provider_condition(code, output) == "auth_required":
        # Authentication/security challenges remain a human-control boundary. Preserve
        # the active ChatGPT session long enough for interactive recovery before fallback.
        return code, output
    if provider_condition(code, output) is None:
        return code, output
    if not fallback_router_available(state):
        return code, output + "\n\n[PASI FALLBACK ROUTER SKIPPED]\noptional fallback route is in a bounded cooldown after a recent failure"
    fallback = command(
        [legacy.sys.executable, str(control_script("pasi_provider_router.py")), "--task", prompt, "--repo", str(state.worktree), "--timeout", "180"],
        Path(state.worktree),
        225.0,
    )
    if fallback[0] == 0 and fallback[1].strip():
        state.fallback_router_disabled_until = ""
        save_state(state)
        return 0, fallback[1]
    fallback_output = fallback[1]
    disable_fallback_router(state, fallback_output or "fallback router returned no usable response")
    return code, output + "\n\n[PASI FALLBACK ROUTER]\n" + fallback_output


def parse_response(response: str) -> tuple[str, str, str, str, bool, dict[str, str]]:
    status, summary, next_task, patch, allow_delete, values = legacy.parse_response(response)
    values["automation_continue"] = "true" if AUTOMATION_CONTINUE_RE.search(response) else "false"
    return status, summary, next_task, patch, allow_delete, values


def completion_contract(status: str, values: dict[str, str]) -> bool:
    return legacy.completion_contract_is_satisfied(status, values)


def completed_task_keys() -> set[str]:
    return {
        key
        for key, value in load_task_ledger().items()
        if str(value.get("status", "")).casefold() == "completed"
    }


def no_change_completion_is_satisfied(
    worktree: Path,
    status: str,
    next_task: str,
    patch: str,
    values: dict[str, str],
    task_already_completed: bool,
) -> bool:
    return (
        legacy.no_change_completion_is_satisfied(worktree, status, next_task, patch, values)
        and bool(values.get("evidence", "").strip())
        and task_already_completed
    )


def continuation_directive(state: OvernightState, _task: str | None = None) -> str:
    """Return task-local continuation guidance.

    The prompt compiler owns the durable prompt layout and full task context.
    This helper remains for callers that need the continuation section directly.
    """
    return """TASK CONTINUATION:
- Work continuously on CURRENT TASK until it is implemented, tested, diagnosed, and verified.
- Inspect the current repository state before editing; do not assume a prior attempt succeeded.
- If the CURRENT TASK is already satisfied by verified repository changes, do not re-implement it or make cosmetic duplicates. Return the required completion contract and a concrete next task.
- If the same failure repeats, change approach rather than repeating the failed path; use only the supplied PREVIOUS FAILURE EVIDENCE.
- After verified completion, set PASI_RESULT_NEXT_TASK to one concrete high-value follow-up. The scheduler owns the full roadmap and will choose/validate the next task; do not reproduce the roadmap in this response.
- If no concrete repository change remains, report PASI_RESULT_REPOSITORY_PROGRESS: stopped with an empty patch. Do not invent work or cosmetic changes.
- If a verified result shows another automation, computer-use, recovery, integration, or security capability is materially necessary, include exactly PASI_AUTOMATION_CONTINUE: true. Otherwise omit it.
- Preserve all authentication, authorization, approval, path, network, and verification boundaries. Pause for human input only when an explicit approval boundary requires it."""

def build_prompt(task: str, state: OvernightState, failure: str = "") -> str:
    return prompt_compiler.compile_task_prompt(
        task,
        run_id=state.run_id,
        task_number=state.task_number,
        attempt=state.current_attempt,
        max_attempts=MAX_ATTEMPTS,
        branch=state.branch,
        worktree=state.worktree,
        phase=state.phase,
        recent_tasks=state.recent_tasks,
        roadmap_tasks=AUTOMATION_TASKS if state.phase == "automation" else ENGINEERING_TASKS,
        previous_failure=failure,
    )


def choose_next_task(state: OvernightState, suggested: str) -> str:
    candidate = re.sub(r"\s+", " ", suggested).strip()
    candidates = AUTOMATION_TASKS if state.phase == "automation" else ENGINEERING_TASKS
    configured = {item.casefold(): item for item in candidates}
    current = state.current_task.casefold().strip()
    if candidate.casefold() == current and current in configured:
        # A completion response that repeats the current roadmap item must advance
        # rather than relying on the bounded recent-task window to break the loop.
        index = next(index for index, item in enumerate(candidates) if item.casefold() == current)
        return candidates[(index + 1) % len(candidates)]

    recent = {item.casefold() for item in state.recent_tasks[-12:]}
    if candidate.casefold() in configured and candidate.casefold() not in recent:
        return configured[candidate.casefold()]
    return choose_unique(candidates, state)


def fast_local_gate(worktree: Path) -> str:
    """Run a bounded changed-file gate for long-running unattended mode."""
    code, output = command(["git", "diff", "--check"], worktree, 60.0)
    if code != 0:
        raise RuntimeError(f"fast local gate diff check failed:\n{output}")

    code, output = command(["git", "diff", "--name-only"], worktree, 30.0)
    if code != 0:
        raise RuntimeError(f"fast local gate could not enumerate changed files:\n{output}")

    changed = [line.strip() for line in output.splitlines() if line.strip()]
    if not changed:
        raise RuntimeError("fast local gate found no changed files after patch application")

    existing = [path for path in changed if (worktree / path).is_file()]
    python_files = [path for path in existing if path.endswith(".py")]
    javascript_files = [path for path in existing if path.endswith(".js")]
    shell_files = [path for path in existing if path.endswith(".sh")]
    json_files = [path for path in existing if path.endswith(".json")]

    checks: list[str] = []

    if python_files:
        code, output = command([legacy.sys.executable, "-m", "py_compile", *python_files], worktree, 120.0)
        if code != 0:
            raise RuntimeError(f"fast local gate Python syntax failed:\n{output}")
        checks.append(f"py_compile:{len(python_files)}")
        code, output = command(["npx", "--yes", "pyright@1.1.411", *python_files], worktree, 180.0)
        if code != 0:
            raise RuntimeError(f"fast local gate pyright failed:\n{output}")
        checks.append(f"pyright:{len(python_files)}")

    for path in javascript_files:
        code, output = command(["node", "--check", path], worktree, 30.0)
        if code != 0:
            raise RuntimeError(f"fast local gate JavaScript syntax failed for {path}:\n{output}")
    if javascript_files:
        checks.append(f"node_check:{len(javascript_files)}")

    for path in shell_files:
        code, output = command(["bash", "-n", path], worktree, 30.0)
        if code != 0:
            raise RuntimeError(f"fast local gate shell syntax failed for {path}:\n{output}")
    if shell_files:
        checks.append(f"bash_check:{len(shell_files)}")

    for path in json_files:
        code, output = command(
            [legacy.sys.executable, "-c", "import json,sys; json.load(open(sys.argv[1], encoding='utf-8'))", path],
            worktree,
            30.0,
        )
        if code != 0:
            raise RuntimeError(f"fast local gate JSON validation failed for {path}:\n{output}")
    if json_files:
        checks.append(f"json_check:{len(json_files)}")

    python_tests: set[str] = {
        path for path in existing
        if path.endswith(".py") and (
            Path(path).name.startswith("test_")
            or "/test_" in path
        )
    }
    node_tests: set[str] = {
        path for path in existing
        if path.endswith(".test.js")
    }

    if any(path.startswith("automation/chromium/pasi-chatgpt/") for path in changed):
        node_tests.update({
            "automation/chromium/pasi-chatgpt/test_extension.js",
            "automation/chromium/pasi-chatgpt/test_recovery.js",
        })
        python_tests.add("automation/chromium/pasi-chatgpt/test_controller_latency.py")

    if any(path.startswith("automation/orchestrator/bridge.py") or path.startswith("automation/orchestrator/test_bridge") for path in changed):
        python_tests.update({
            "automation/orchestrator/test_bridge.py",
            "automation/orchestrator/test_bridge_edge_cases.py",
        })

    if any(path.startswith("automation/orchestrator/state.py") or path.startswith("automation/orchestrator/test_state") for path in changed):
        python_tests.update({
            "automation/orchestrator/test_state.py",
            "automation/orchestrator/test_state_corruption_regression.py",
        })

    if any(path.startswith("scripts/pasi_overnight_engine_v2.py") or path.startswith("scripts/test_pasi_overnight_engine_v2.py") for path in changed):
        python_tests.add("scripts/test_pasi_overnight_engine_v2.py")

    if any(path.startswith("scripts/pasi_chat.py") or path.startswith("scripts/test_pasi_chat") for path in changed):
        python_tests.update({
            "scripts/test_pasi_chat.py",
            "scripts/test_pasi_chat_routing.py",
            "scripts/test_pasi_chat_guard.py",
        })

    python_tests = {path for path in python_tests if (worktree / path).is_file()}
    node_tests = {path for path in node_tests if (worktree / path).is_file()}

    if python_tests:
        code, output = command(
            [legacy.sys.executable, "-m", "pytest", "-q", *sorted(python_tests)],
            worktree,
            300.0,
        )
        if code != 0:
            raise RuntimeError(f"fast local gate targeted pytest failed:\n{output}")
        checks.append(f"pytest:{len(python_tests)}")

    if node_tests:
        code, output = command(["node", "--test", *sorted(node_tests)], worktree, 180.0)
        if code != 0:
            raise RuntimeError(f"fast local gate targeted Node tests failed:\n{output}")
        checks.append(f"node_tests:{len(node_tests)}")

    return "FAST LOCAL GATE PASSED: " + ", ".join(checks) + f"; changed={len(changed)} files"


def verify_and_commit(worktree: Path, branch: str, task: str, patch: str, allow_delete: bool, *, push: bool) -> tuple[str, str]:
    validate_patch_paths(patch, allow_delete, worktree)
    gate_mode = os.environ.get("PASI_LOCAL_GATE_MODE", "full").strip().lower() or "full"
    verify_started_at = now_utc().isoformat()
    log_event(
        "verify_started",
        task=task,
        gate_mode=gate_mode,
        started_at=verify_started_at,
    )
    code, output = command(
        ["git", "apply", "--check", "--whitespace=nowarn"],
        worktree,
        60.0,
        input_text=patch,
    )
    if code != 0:
        raise RuntimeError(f"git apply --check failed:\n{output}")
    code, output = command(
        ["git", "apply", "--whitespace=nowarn"],
        worktree,
        60.0,
        input_text=patch,
    )
    if code != 0:
        raise RuntimeError(f"git apply failed:\n{output}")
    if gate_mode == "fast":
        output = fast_local_gate(worktree)
        log_event("fast_local_gate_passed")
    elif gate_mode in {"", "full"}:
        code, output = command(["bash", "scripts/check_all.sh"], worktree, 900.0)
        if code != 0:
            raise RuntimeError(f"canonical validation failed:\n{output}")
    else:
        raise RuntimeError(
            f"unsupported PASI_LOCAL_GATE_MODE={gate_mode!r}; expected fast or full"
        )
    code, status = command(["git", "status", "--porcelain"], worktree, 30.0)
    if code != 0 or not status:
        raise RuntimeError("verification passed but no repository changes remain")
    changed_files = [line.strip() for line in status.splitlines() if line.strip()]
    log_event(
        "verify_finished",
        task=task,
        gate_mode=gate_mode,
        finished_at=now_utc().isoformat(),
        changed_files=len(changed_files),
    )
    commit = legacy.commit_and_push(worktree, branch, task, push, paths=legacy.patch_paths_from_diff(patch))
    code, status = command(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        worktree,
        30.0,
    )
    if code != 0:
        raise RuntimeError(f"post-commit hygiene check failed: {status}")
    if status.strip():
        raise RuntimeError(f"post-commit hygiene check found uncommitted files:\n{status}")
    if push:
        promotion = command(
            [
                legacy.sys.executable,
                str(control_script("pasi_promote.py")),
                "--commit",
                commit,
                "--branch",
                branch,
                "--task",
                task,
                "--json",
            ],
            REPO_ROOT,
            90.0,
        )
        if promotion[0] == 0:
            output = output + "\n\n[PASI PROMOTION]\n" + promotion[1]
        else:
            log_event("promotion_deferred", commit=commit, branch=branch, error=promotion[1][-4000:])
            output = output + "\n\n[PASI PROMOTION DEFERRED]\n" + promotion[1][-4000:]
    return commit, output


def standby_until_ready(
    state: OvernightState,
    *,
    wait_for_auth: bool = False,
    max_wait_seconds: float | None = None,
) -> bool:
    logged = False
    auth_logged = False
    run_deadline = datetime.fromisoformat(state.deadline_at)
    wait_deadline = run_deadline
    if max_wait_seconds is not None:
        if max_wait_seconds <= 0:
            raise ValueError("max_wait_seconds must be positive")
        wait_deadline = min(run_deadline, now_utc() + timedelta(seconds=max_wait_seconds))
    while not STOP and now_utc() < wait_deadline:
        try:
            ensure_services()
        except Exception as exc:
            log_event("service_recovery_failed", error=str(exc)[-4_000:])

        if browser_auth_required():
            if not wait_for_auth:
                log_event("standby_auth_required")
                return False
            if not auth_logged:
                log_event(
                    "auth_recovery_wait_started",
                    reason="interactive ChatGPT authentication/security challenge detected; preserving the active conversation while waiting for human-visible recovery",
                    max_wait_seconds=max_wait_seconds,
                )
                auth_logged = True
            remaining = (wait_deadline - now_utc()).total_seconds()
            time.sleep(min(AUTH_RECOVERY_POLL_SECONDS, max(0.5, remaining)))
            continue

        if runtime_watchdog_is_live():
            if logged or auth_logged:
                log_event("standby_recovered")
            return True

        if not logged:
            log_event(
                "standby_started",
                reason="browser controller/extension heartbeat is stale; waiting for browser recovery while keeping local services healthy",
            )
            logged = True

        remaining = (wait_deadline - now_utc()).total_seconds()
        time.sleep(min(STANDBY_SECONDS, max(1.0, remaining)))
    if auth_logged and browser_auth_required() and not STOP and now_utc() < run_deadline:
        log_event("auth_recovery_wait_expired", max_wait_seconds=max_wait_seconds)
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
            gate_evidence = automation_gate_evidence(state)
            log_event(
                "automation_gate_evidence",
                gate=gate_evidence["automation_gate"],
                opportunity=gate_evidence["automation_opportunity"],
                evidence=gate_evidence["automation_evidence"][-1000:],
            )
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
                log_event("auth_recovery_required", reason="ChatGPT authentication challenge", task_number=state.task_number)
                recovered = standby_until_ready(
                    state,
                    wait_for_auth=True,
                    max_wait_seconds=AUTH_RECOVERY_WAIT_SECONDS,
                )
                if recovered:
                    failure = ""
                    log_event("auth_recovery_resumed", task_number=state.task_number)
                    continue
                if STOP or now_utc() >= datetime.fromisoformat(state.deadline_at):
                    return
                log_event("fallback_provider_route", reason="ChatGPT authentication challenge persisted beyond bounded human-recovery wait", task_number=state.task_number)
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
            contract_ok = completion_contract(status, values)
            if contract_ok and no_change_completion_is_satisfied(
                Path(state.worktree),
                status,
                next_task,
                patch,
                values,
                task_key(state.current_task) in completed_task_keys(),
            ):
                state.completed_tasks += 1
                evidence_text = summary or values.get("evidence", "validated task already satisfied; no repository change remained")
                record_task_ledger(
                    state.current_task,
                    "completed",
                    evidence=evidence_text,
                    phase=state.phase,
                    automation_continue=values.get("automation_continue", "").lower() == "true",
                )
                state.last_result = evidence_text
                state.next_task = choose_next_task(state, next_task)
                state.recent_tasks.append(state.current_task)
                state.current_task = state.next_task
                state.next_task = ""
                state.current_attempt = 0
                save_state(state)
                log_event(
                    "task_completed_no_change",
                    phase=state.phase,
                    task_number=state.task_number,
                    reason="task already satisfied and repository remained clean",
                    next_task=state.current_task,
                )
                failure = ""
                finished = True
                break
            if not contract_ok or not patch:
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
            record_task_ledger(
                state.current_task,
                "completed",
                commit=commit,
                evidence=summary or verification[-3000:],
                phase=state.phase,
                automation_continue=values.get("automation_continue", "").lower() == "true",
            )
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


def finish_reason(*, stop_requested: bool, deadline_reached: bool) -> str:
    if deadline_reached:
        return "deadline_reached"
    if stop_requested:
        return "stopped"
    return "unexpected_early_exit"


def finish_state(state: OvernightState, reason: str) -> None:
    state.stop_reason = reason
    state.last_result = reason
    save_state(state)
    log_event("run_finished", phase=state.phase, completed_tasks=state.completed_tasks, failed_tasks=state.failed_tasks, provider_limit_pauses=state.provider_limit_pauses, reason=reason)


def main() -> int:
    global STOP
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
            run_id = f"overnight-{uuid.uuid4().hex}"
            selected_task, guard_applied, prior_repeats = choose_run_start_task(
                "automation", args.task.strip(), run_id
            )
            state = OvernightState(
                schema_version=2,
                run_id=run_id,
                started_at=started.isoformat(),
                deadline_at=(started + timedelta(hours=args.hours)).isoformat(),
                worktree=str(args.worktree.expanduser().resolve()),
                branch=args.branch,
                phase="automation",
                current_task=selected_task,
                requested_task=args.task.strip(),
            )
            resume = False
            save_state(state)
            log_event("run_started", **state.to_dict(), push=not args.no_push)
            if guard_applied:
                log_event(
                    "roadmap_loop_guard",
                    phase=state.phase,
                    repeated_task=state.requested_task or AUTOMATION_TASKS[0],
                    consecutive_prior_runs=prior_repeats,
                    skipped_to=state.current_task,
                    reason="same roadmap selection recurred across consecutive runs",
                )

        ensure_worktree(Path(state.worktree), state.branch, resume=resume)
        children = ensure_services()
        run(state, push=not args.no_push)
        if not state.stop_reason:
            finish_state(
                state,
                finish_reason(
                    stop_requested=STOP,
                    deadline_reached=now_utc() >= datetime.fromisoformat(state.deadline_at),
                ),
            )
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
