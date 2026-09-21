from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import signal
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from scripts import pasi_hybrid_planner as hybrid_planner
from scripts import pasi_prompt_compiler as prompt_compiler
from scripts.pasi_stage_events import StageTimer, classify_failure

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = Path(os.environ.get("PASI_RUNTIME_DIR", str(Path.home() / ".pasi" / "overnight"))).expanduser().resolve()
STATE_PATH = RUNTIME_DIR / "state.json"
EVENT_LOG = RUNTIME_DIR / "events.jsonl"
PID_PATH = RUNTIME_DIR / "runner.pid"
ROADMAP_LOOP_GUARD_PATH = RUNTIME_DIR / "roadmap-loop-guard.json"
BRIDGE_URL = "http://127.0.0.1:8765"
CONTROLLER_SOURCE_PATH = REPO_ROOT / "automation" / "chromium" / "pasi-chatgpt" / "content.js"
BRIDGE_QUEUE_PATH = REPO_ROOT / ".ai" / "queue.json"
CONTROLLER_MANIFEST_PATH = REPO_ROOT / "automation" / "chromium" / "pasi-chatgpt" / "manifest.json"
MAX_PATCH_BYTES = 250_000
MAX_OUTPUT_CHARS = 20_000
PROTECTED_UNATTENDED_PATHS = frozenset({
    "scripts/check_all.sh",
    "scripts/check_offline.sh",
    "scripts/pasi_overnight_hardening.py",
    "scripts/pasi_overnight_engine_v2.py",
    "automation/chromium/pasi-chatgpt/manifest.json",
})
PROTECTED_UNATTENDED_PREFIXES = (
    ".github/",
    ".githooks/",
    "hooks/",
)
DEFAULT_WORKTREE = Path.home() / ".pasi-worktrees" / "personal-ai-system-overnight"
DEFAULT_HOURS = 10.0
MIN_HOURS = 8.0
MAX_HOURS = float("inf")
MAX_ATTEMPTS = 3
TASK_TIMEOUT_SECONDS = 900.0
WATCHDOG_MAX_AGE_SECONDS = 30.0
STANDBY_SECONDS = 30.0
AUTOMATION_TASKS_PER_GATE = 2
MAX_PROVIDER_LIMIT_PAUSES = 3
PROVIDER_LIMIT_EXHAUSTED_COOLDOWN_SECONDS = 900.0
AUTH_RECOVERY_WAIT_SECONDS = 300.0
AUTH_RECOVERY_POLL_SECONDS = 5.0
FALLBACK_ROUTER_COOLDOWN_SECONDS = 900.0
ROADMAP_CONSECUTIVE_RUN_LIMIT = 2
ROADMAP_LOOP_GUARD_HISTORY_LIMIT = 24
TASK_LEDGER_PATH = RUNTIME_DIR / "task-ledger.json"
DEFAULT_ROADMAP_PATH = REPO_ROOT / "roadmaps" / "pasi-default.json"
ROADMAP_OVERLAY_PATH = RUNTIME_DIR / "roadmap-decompositions.json"
PLANNER_AI_TIMEOUT_SECONDS = 1.5
MAX_TASK_TEXT_CHARS = 4000
CONTROL_SCRIPTS_ROOT = REPO_ROOT / "scripts"

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
    "allow_delete": re.compile(
        r"^PASI_RESULT_ALLOW_DELETE:\s*(true|false)$",
        re.MULTILINE | re.IGNORECASE,
    ),
}
AUTOMATION_CONTINUE_RE = re.compile(
    r"^PASI_AUTOMATION_CONTINUE:\s*true$",
    re.MULTILINE | re.IGNORECASE,
)
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
    task_retry_cycle: int = 0
    last_failure_signature: str = ""
    same_failure_cycles: int = 0
    automation_tasks_since_gate: int = 0
    automation_gates: int = 0
    provider_limit_pauses: int = 0
    fallback_router_disabled_until: str = ""
    last_provider: str = "chatgpt_browser"
    last_result: str = ""
    next_task: str = ""
    stop_reason: str = ""
    recent_tasks: list[str] = field(default_factory=list)
    roadmap_path: str = ""
    current_task_id: str = ""

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
            "task_retry_cycle": self.task_retry_cycle,
            "last_failure_signature": self.last_failure_signature,
            "same_failure_cycles": self.same_failure_cycles,
            "automation_tasks_since_gate": self.automation_tasks_since_gate,
            "automation_gates": self.automation_gates,
            "provider_limit_pauses": self.provider_limit_pauses,
            "fallback_router_disabled_until": self.fallback_router_disabled_until,
            "last_provider": self.last_provider,
            "last_result": self.last_result,
            "next_task": self.next_task,
            "stop_reason": self.stop_reason,
            "recent_tasks": self.recent_tasks[-12:],
            "roadmap_path": self.roadmap_path,
            "current_task_id": self.current_task_id,
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
            task_retry_cycle=int(raw.get("task_retry_cycle", 0)),
            last_failure_signature=str(raw.get("last_failure_signature", "")),
            same_failure_cycles=int(raw.get("same_failure_cycles", 0)),
            automation_tasks_since_gate=int(raw.get("automation_tasks_since_gate", 0)),
            automation_gates=int(raw.get("automation_gates", 0)),
            provider_limit_pauses=int(raw.get("provider_limit_pauses", 0)),
            fallback_router_disabled_until=str(raw.get("fallback_router_disabled_until", "")),
            last_provider=str(raw.get("last_provider", "chatgpt_browser")),
            last_result=str(raw.get("last_result", "")),
            next_task=str(raw.get("next_task", "")),
            stop_reason=str(raw.get("stop_reason", "")),
            recent_tasks=recent_tasks[-12:],
            roadmap_path=str(raw.get("roadmap_path", "")),
            current_task_id=str(raw.get("current_task_id", "")),
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
    task_id: str = "",
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
        "task_id": task_id.strip(),
        "updated_at": now_utc().isoformat(),
    }
    save_task_ledger(ledger)


def valid_next_task(candidate: str, current_task: str, recent_tasks: Sequence[str]) -> str:
    value = re.sub(r"\s+", " ", candidate).strip()
    if not value or len(value) > MAX_TASK_TEXT_CHARS or any(ord(char) < 32 for char in value):
        return ""
    lowered = value.casefold()
    recent = {item.casefold().strip() for item in recent_tasks}
    if lowered == current_task.casefold().strip() or lowered in recent:
        return ""
    if task_key(value) in completed_task_keys():
        return ""
    return value




def normalize_patch(patch: str) -> str:
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
        if line.strip().startswith(chr(96) * 3):
            lines = lines[:index]
            break
    return "\n".join(lines).strip() + "\n"




def repository_worktree_is_clean(worktree: Path) -> bool:
    code, status = command(["git", "status", "--porcelain", "--untracked-files=all"], worktree, 30.0)
    return code == 0 and not status.strip()




def run_validation_sandbox(worktree: Path, timeout: float = 900.0) -> str:
    """Run offline validation from an isolated filesystem/network view."""
    if not shutil.which("bwrap"):
        raise RuntimeError(
            "bubblewrap is required for network/filesystem-isolated validation; "
            "install the bubblewrap package before running PASI unattended"
        )

    import tempfile

    with tempfile.TemporaryDirectory(prefix="pasi-validation-") as temp_dir:
        sandbox_root = Path(temp_dir)
        sandbox_repo = sandbox_root / "repo"
        shutil.copytree(
            worktree,
            sandbox_repo,
            symlinks=True,
            ignore=shutil.ignore_patterns(
                ".git",
                ".runtime",
                "__pycache__",
                "*.pyc",
            ),
        )

        code, output = command(
            ["git", "init", "-b", "pasi-validation"],
            sandbox_repo,
            30.0,
        )
        if code != 0:
            raise RuntimeError(f"could not initialize validation sandbox repository: {output}")
        code, output = command(
            ["git", "add", "-A"],
            sandbox_repo,
            30.0,
        )
        if code != 0:
            raise RuntimeError(f"could not stage validation sandbox snapshot: {output}")

        venv_path = REPO_ROOT / ".venv"
        path_value = "/usr/local/bin:/usr/bin:/bin"
        venv_bind: list[str] = []
        if venv_path.is_dir():
            path_value = "/pasi-venv/bin:" + path_value
            venv_bind = ["--ro-bind", str(venv_path), "/pasi-venv"]

        env_values = {
            "PATH": path_value,
            "HOME": "/tmp/pasi-validation-home",
            "LANG": os.environ.get("LANG", "C.UTF-8"),
            "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
            "PYTHONPATH": "/workspace",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_ASKPASS": "/bin/false",
            "CI": "1",
        }
        base = [
            "env",
            "-i",
            *[f"{key}={value}" for key, value in env_values.items()],
            "bash",
            "scripts/check_all.sh",
        ]
        sandbox_command = [
            "bwrap",
            "--ro-bind", "/usr", "/usr",
            "--ro-bind", "/bin", "/bin",
            "--ro-bind", "/lib", "/lib",
            "--ro-bind", "/lib64", "/lib64",
            "--ro-bind", "/etc", "/etc",
            "--dev", "/dev",
            "--proc", "/proc",
            "--tmpfs", "/tmp",
            "--tmpfs", "/home",
            "--tmpfs", "/root",
            "--tmpfs", "/mnt",
            "--tmpfs", "/media",
            "--bind", str(sandbox_repo), "/workspace",
            *venv_bind,
            "--unshare-net",
            "--chdir", "/workspace",
            *base,
        ]
        code, output = command(sandbox_command, sandbox_repo, timeout)
        if code == 0:
            return output
        raise RuntimeError(f"sandboxed canonical validation failed:\n{output}")




def commit_and_push(worktree: Path, branch: str, task: str, push: bool) -> str:
    code, output = command(["git", "add", "-A"], worktree, 30.0)
    if code != 0:
        raise RuntimeError(f"git add failed: {output}")
    code, output = command(["git", "diff", "--cached", "--quiet"], worktree, 30.0)
    if code == 0:
        raise RuntimeError("task completed without producing a commit")
    message = re.sub(r"[^A-Za-z0-9 .:_/-]+", "", task).strip()[:65] or "overnight PASI task"
    commit_tag = f"task-{task_key(task)[:12]}"
    code, output = command(["git", "commit", "-m", f"pasi: {commit_tag} {message}"], worktree, 120.0)
    if code != 0:
        raise RuntimeError(f"git commit failed: {output}")
    code, commit = command(["git", "rev-parse", "HEAD"], worktree, 15.0)
    if code != 0:
        raise RuntimeError(f"could not read commit: {commit}")
    if push:
        code, output = command(["git", "push", "--set-upstream", "origin", branch], worktree, 180.0)
        if code != 0:
            raise RuntimeError(f"git push failed: {output}")
    return commit




def reconcile_committed_task(state: OvernightState) -> bool:
    """Recover a commit acknowledged by Git but not yet written to the task ledger."""
    normalized = re.sub(r"\s+", " ", state.current_task).strip()
    if not normalized:
        return False
    key = task_key(normalized)
    entry = load_task_ledger().get(key)
    if isinstance(entry, dict) and str(entry.get("status", "")).casefold() == "completed":
        return False
    worktree = Path(state.worktree)
    if not repository_worktree_is_clean(worktree):
        return False
    code, subject = command(["git", "log", "-1", "--format=%s"], worktree, 15.0)
    if code != 0 or f"task-{key[:12]}" not in subject:
        return False
    code, commit = command(["git", "rev-parse", "HEAD"], worktree, 15.0)
    if code != 0 or not commit.strip():
        return False
    record_task_ledger(
        normalized,
        "completed",
        commit=commit.strip(),
        evidence="Recovered completed task from an already-created tagged Git commit after restart.",
        phase=state.phase,
        task_id=state.current_task_id,
    )
    state.completed_tasks += 1
    if state.phase == "automation":
        state.automation_tasks_since_gate += 1
    state.recent_tasks.append(normalized)
    state.current_attempt = 0
    state.next_task = ""
    state.current_task = choose_next_task(state, "")
    save_state(state)
    log_event(
        "task_recovered_from_commit",
        phase=state.phase,
        task_number=state.task_number,
        commit=commit.strip(),
        recovered_task=normalized,
        next_task=state.current_task,
    )
    return True




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


def planner_roadmap_path(state: OvernightState | None = None, explicit: Path | None = None) -> Path:
    candidate = explicit
    if candidate is None and state is not None and state.roadmap_path.strip():
        candidate = Path(state.roadmap_path)
    if candidate is None:
        env_path = os.environ.get("PASI_ROADMAP_PATH", "").strip()
        candidate = Path(env_path) if env_path else DEFAULT_ROADMAP_PATH
    return candidate.expanduser().resolve()


def planner_ai_ranker():
    enabled = os.environ.get("PASI_PLANNER_AI_RANK", "").strip().casefold() in {"1", "true", "yes", "on"}
    model = os.environ.get("PASI_PLANNER_MODEL", "").strip() or os.environ.get("OLLAMA_MODEL", "").strip()
    if not enabled or not model:
        return None
    return lambda candidates: hybrid_planner.ollama_ranker(
        candidates,
        timeout_seconds=PLANNER_AI_TIMEOUT_SECONDS,
        model=model,
    )


def planner_ai_decompose_enabled() -> bool:
    return os.environ.get("PASI_PLANNER_AI_DECOMPOSE", "").strip().casefold() in {"1", "true", "yes", "on"}


def load_planner_tasks(state: OvernightState, phase: str | None = None) -> tuple[hybrid_planner.TaskSpec, ...]:
    source = planner_roadmap_path(state)
    tasks = hybrid_planner.load_roadmap_with_overlay(source, ROADMAP_OVERLAY_PATH)
    if phase is None:
        return tasks
    return tuple(task for task in tasks if task.phase == phase)


def task_id_for_prompt(tasks: Sequence[hybrid_planner.TaskSpec], prompt: str) -> str:
    normalized = " ".join(prompt.split())
    for task in tasks:
        if " ".join(task.execution_text().split()) == normalized:
            return task.id
    return ""


def select_planner_task(
    state: OvernightState,
    *,
    phase: str | None = None,
) -> hybrid_planner.PlannerDecision:
    tasks = load_planner_tasks(state)
    decision = hybrid_planner.select_task(
        tasks,
        load_task_ledger(),
        phase=phase,
        ai_ranker=planner_ai_ranker(),
    )
    selected = decision.selected
    if selected is not None and selected.splittable and selected.estimated_size in {"large", "very_large"} and planner_ai_decompose_enabled():
        try:
            children = hybrid_planner.ai_decompose_with_ollama(
                selected,
                timeout_seconds=PLANNER_AI_TIMEOUT_SECONDS,
            )
            hybrid_planner.save_decomposition_overlay(
                ROADMAP_OVERLAY_PATH,
                parent=selected,
                children=children,
            )
            log_event(
                "planner_decomposed_task",
                parent_id=selected.id,
                child_ids=[child.id for child in children],
                reason="eligible task exceeded configured planner size threshold",
            )
            tasks = load_planner_tasks(state)
            decision = hybrid_planner.select_task(
                tasks,
                load_task_ledger(),
                phase=phase,
                ai_ranker=planner_ai_ranker(),
            )
        except (hybrid_planner.PlannerError, OSError, TimeoutError):
            log_event(
                "planner_decomposition_fallback",
                task_id=selected.id,
                reason="AI decomposition unavailable or rejected; retaining original eligible task",
            )
    log_event(
        "planner_selection",
        phase=phase or state.phase,
        mode=decision.mode,
        reason=decision.reason,
        ai_used=decision.ai_used,
        eligible_ids=list(decision.eligible_ids),
        selected_id=decision.selected.id if decision.selected else "",
    )
    return decision


def choose_run_start_task(
    phase: str,
    requested_task: str,
    run_id: str,
    roadmap_path: Path | None = None,
) -> tuple[str, bool, int]:
    source = roadmap_path.expanduser().resolve() if roadmap_path else planner_roadmap_path()
    tasks = hybrid_planner.load_roadmap_with_overlay(source, ROADMAP_OVERLAY_PATH)
    candidates = tuple(task for task in tasks if task.phase == phase)
    candidate_text = re.sub(r"\s+", " ", requested_task).strip()
    candidate = None
    for task in candidates:
        if candidate_text.casefold() in {task.id.casefold(), task.title.casefold(), task.execution_text().casefold()}:
            candidate = task
            break
    if candidate is None and candidate_text:
        return candidate_text, False, 0
    if candidate is None:
        decision = hybrid_planner.select_task(
            tasks,
            load_task_ledger(),
            phase=phase,
            ai_ranker=planner_ai_ranker(),
        )
        if decision.selected is None:
            raise RuntimeError(f"roadmap has no eligible {phase} task")
        candidate = decision.selected

    history = load_roadmap_selection_history()
    prior_repeats = consecutive_roadmap_selection_count(history, phase, candidate.execution_text())
    guard_applied = prior_repeats >= ROADMAP_CONSECUTIVE_RUN_LIMIT
    if guard_applied and len(candidates) > 1:
        ordered = [task for task in candidates if task.id != candidate.id]
        candidate = ordered[0]

    updated = [
        *history,
        {
            "phase": phase,
            "task": candidate.execution_text(),
            "run_id": run_id,
            "timestamp": now_utc().isoformat(),
        },
    ]
    save_roadmap_selection_history(updated)
    return candidate.execution_text(), guard_applied, prior_repeats


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
    # Use the same worktree-aware patch policy as the weeklong hardening wrapper.
    # The local import avoids the module's intentional legacy/hardening dependency cycle.
    from scripts import pasi_overnight_hardening as hardening

    hardening.validate_patch_paths(patch, allow_delete, worktree)


def validate_git_resolved_paths(worktree: Path, summary: str) -> None:
    root = worktree.resolve()
    fields: list[str] = []
    for token in summary.split("\x00"):
        if not token:
            continue
        if "\t" in token:
            parts = token.split("\t")
            if len(parts) != 3:
                raise RuntimeError("git apply returned an unexpected numstat record")
            fields.append(parts[2])
        else:
            fields.append(token)

    for path_value in fields:
        if not path_value or path_value == "/dev/null":
            continue
        candidate = (root / path_value).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise RuntimeError(f"git apply resolved an unsafe path: {path_value}") from exc
        if path_value in PROTECTED_UNATTENDED_PATHS or any(
            path_value.startswith(prefix) for prefix in PROTECTED_UNATTENDED_PREFIXES
        ):
            raise RuntimeError(
                f"git apply resolved a protected unattended path: {path_value}"
            )


def apply_patch(worktree: Path, patch: str, allow_delete: bool) -> str:
    validate_patch_paths(patch, allow_delete, worktree)
    code, summary = command(
        ["git", "apply", "--numstat", "-z", "-"],
        worktree,
        60.0,
        input_text=patch,
    )
    if code != 0:
        raise RuntimeError(f"git apply path resolution failed:\n{summary}")
    validate_git_resolved_paths(worktree, summary)
    code, output = command(
        ["git", "apply", "--check", "--whitespace=nowarn", "-"],
        worktree,
        60.0,
        input_text=patch,
    )
    if code != 0:
        raise RuntimeError(f"git apply --check failed:\n{output}")
    code, output = command(
        ["git", "apply", "--whitespace=nowarn", "-"],
        worktree,
        60.0,
        input_text=patch,
    )
    if code != 0:
        raise RuntimeError(f"git apply failed:\n{output}")
    return output


def control_script(name: str) -> Path:
    candidate = (CONTROL_SCRIPTS_ROOT / name).resolve()
    try:
        candidate.relative_to(CONTROL_SCRIPTS_ROOT.resolve())
    except ValueError as exc:
        raise ValueError(f"control script escapes launcher root: {name}") from exc
    if not candidate.is_file():
        raise FileNotFoundError(f"control script is missing from launcher checkout: {candidate}")
    return candidate


def queue_file_bytes() -> int | None:
    try:
        return BRIDGE_QUEUE_PATH.stat().st_size
    except OSError:
        return None


def extract_operation_id(output: str) -> str | None:
    match = re.search(
        r"(?:Prompt operation|Retry prompt operation|Resuming persisted ChatGPT operation|GitHub fallback prompt operation):\s*([A-Za-z0-9._:-]+)",
        output or "",
    )
    return match.group(1) if match else None


def bridge_operation(operation_id: str) -> dict[str, Any] | None:
    token = os.environ.get("PASI_BRIDGE_TOKEN", "").strip()
    if not token:
        try:
            token = (Path.home() / ".pasi" / "bridge-token").read_text(encoding="utf-8").strip()
        except OSError:
            return None
    request = urllib.request.Request(
        f"{BRIDGE_URL}/operation?operation_id={urllib.parse.quote(operation_id, safe='')}",
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=3.0) as response:
            payload = json.loads(response.read(2_000_000).decode("utf-8"))
    except (OSError, urllib.error.URLError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    operation = payload.get("operation") if isinstance(payload, dict) else None
    return dict(operation) if isinstance(operation, dict) else None


def embedded_operation_metrics(output: str) -> dict[str, Any] | None:
    match = re.search(r"^PASI_OPERATION_METRICS: (.+)$", output, re.MULTILINE)
    if not match:
        return None
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    return dict(payload) if isinstance(payload, dict) else None


def emit_operation_metrics(task: str, attempt: int, output: str) -> None:
    operation_id = extract_operation_id(output)
    if not operation_id:
        return
    log_event(
        "prompt_queued",
        task_id=task_key(task),
        attempt=attempt,
        operation_id=operation_id,
        queue_file_bytes=queue_file_bytes(),
    )
    operation = embedded_operation_metrics(output) or bridge_operation(operation_id)
    if not operation:
        return
    timing = operation.get("timing")
    if isinstance(timing, dict):
        log_event(
            "browser_timing",
            task_id=task_key(task),
            attempt=attempt,
            operation_id=operation_id,
            **timing,
        )
    response_text = operation.get("response_text")
    if isinstance(response_text, str):
        log_event(
            "response_received",
            task_id=task_key(task),
            attempt=attempt,
            operation_id=operation_id,
            chars=len(response_text),
        )
    events = operation.get("recovery_events")
    if isinstance(events, list):
        for event in events:
            if not isinstance(event, dict):
                continue
            duration = event.get("recovery_duration_ms")
            if isinstance(duration, (int, float)) and not isinstance(duration, bool):
                log_event(
                    "recovery_finished",
                    task_id=task_key(task),
                    attempt=attempt,
                    operation_id=operation_id,
                    reason=str(event.get("recovery_reason") or event.get("reason") or "unknown"),
                    duration_ms=duration,
                    outcome=str(event.get("outcome") or ""),
                )


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
        children.append(subprocess.Popen([sys.executable, "-m", "automation.orchestrator.bridge"], cwd=REPO_ROOT))
    deadline = time.monotonic() + 20.0
    while time.monotonic() < deadline:
        if healthy(f"{BRIDGE_URL}/health"):
            return children
        time.sleep(0.5)
    raise RuntimeError("local PASI bridge service did not become healthy")


def worktree_start_ref() -> str:
    configured = os.environ.get("PASI_OVERNIGHT_BASE_REF", "").strip()
    return configured or "origin/main"


def find_worktree_for_branch(branch: str) -> Path | None:
    code, output = command(["git", "worktree", "list", "--porcelain"], REPO_ROOT, 30.0)
    if code != 0:
        return None
    path_value: str | None = None
    branch_value: str | None = None
    for raw_line in output.splitlines() + [""]:
        line = raw_line.strip()
        if line.startswith("worktree "):
            path_value = line[len("worktree "):].strip()
        elif line.startswith("branch refs/heads/"):
            branch_value = line[len("branch refs/heads/"):].strip()
        elif not line:
            if branch_value == branch and path_value:
                return Path(path_value).expanduser().resolve()
            path_value = None
            branch_value = None
    return None


def ensure_worktree(path: Path, branch: str, *, resume: bool) -> Path:
    start_ref = worktree_start_ref()
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not (path / ".git").exists():
        existing = find_worktree_for_branch(branch)
        if existing is not None:
            log_event("worktree_reused_by_branch", requested_path=str(path), worktree=str(existing), branch=branch)
            path = existing
        else:
            code, output = command(
                ["git", "worktree", "add", "-B", branch, str(path), start_ref],
                REPO_ROOT,
                60.0,
            )
            if code != 0:
                raise RuntimeError(f"could not create overnight worktree from {start_ref}: {output}")
            return path
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

    code, counts = command(["git", "rev-list", "--left-right", "--count", f"{branch}...{start_ref}"], path, 30.0)
    if code != 0:
        raise RuntimeError(f"could not compare overnight branch with {start_ref}: {counts}")
    parts = counts.split()
    if len(parts) != 2:
        raise RuntimeError(f"could not parse overnight branch ancestry: {counts}")
    try:
        ahead, behind = int(parts[0]), int(parts[1])
    except ValueError as exc:
        raise RuntimeError(f"could not parse overnight branch ancestry: {counts}") from exc
    if behind > 0 and ahead == 0:
        merge_code, merge_output = command(["git", "merge", "--ff-only", start_ref], path, 60.0)
        if merge_code != 0:
            raise RuntimeError(f"could not fast-forward overnight branch to {start_ref}: {merge_output}")
        log_event("resume_branch_fast_forwarded", branch=branch, commits=behind)
    elif behind > 0 and ahead > 0:
        log_event("resume_branch_diverged", branch=branch, ahead=ahead, behind=behind)
    return path


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


def expected_controller_version(source_path: Path | None = None) -> str | None:
    controller_path = source_path or CONTROLLER_SOURCE_PATH
    try:
        text = controller_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    match = re.search(r"\bCONTROLLER_VERSION\s*=\s*['\"]([^'\"]+)['\"]", text)
    return match.group(1).strip() if match and match.group(1).strip() else None


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


def sanitize_failure_evidence(code: int, output: str) -> str:
    condition = provider_condition(code, output)
    bounded = re.sub(r"\s+", " ", str(output or "")).strip()
    return f"failure_class={condition or 'task_error'}; exit_code={code}; detail={bounded[:800]}"


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
    state.last_provider = "chatgpt_browser"
    prompt = build_prompt(task, state, failure)
    log_event(
        "prompt_compiled",
        pattern_version=prompt_compiler.PROMPT_PATTERN_VERSION,
        prompt_hash=prompt_compiler.prompt_hash(prompt),
        prompt_chars=len(prompt),
        task_key=task_key(task),
        task_number=state.task_number,
        attempt=state.current_attempt,
    )
    code, output = command(
        [sys.executable, str(control_script("pasi_chat_guard.py")), prompt, "--github", "public", "--timeout", str(TASK_TIMEOUT_SECONDS), "--repo", state.worktree],
        REPO_ROOT,
        TASK_TIMEOUT_SECONDS + 45.0,
    )
    condition = provider_condition(code, output)
    if condition is None:
        return code, output
    if condition == "auth_required":
        # Authentication/security challenges remain a human-control boundary.
        # The run loop waits for interactive recovery before considering fallback.
        return code, output
    # Runtime-guard and provider-limit failures stay on the primary path. They
    # are infrastructure recovery conditions, not authorization to switch providers.
    return code, sanitize_failure_evidence(code, output)



def parse_response(response: str) -> tuple[str, str, str, str, bool, dict[str, str]]:
    if not isinstance(response, str):
        raise ValueError("model response must be text")
    values: dict[str, str] = {}
    missing_or_duplicate: list[str] = []
    optional_markers = {"next_task"}
    for key, pattern in MARKERS.items():
        matches = pattern.findall(response)
        if len(matches) != 1:
            if key in optional_markers and not matches:
                values[key] = ""
                continue
            missing_or_duplicate.append(key)
            if matches:
                values[key] = matches[0].strip()
        else:
            values[key] = matches[0].strip()
    if missing_or_duplicate:
        raise ValueError(
            "PASI response contract must contain each marker exactly once: "
            + ", ".join(sorted(missing_or_duplicate))
        )
    if response.count(PATCH_BEGIN) != 1 or response.count(PATCH_END) != 1:
        raise ValueError("PASI response patch fence must occur exactly once")
    status = values["status"].strip().lower()
    summary = values["summary"].strip()
    next_task = values["next_task"].strip()
    allow_delete = values["allow_delete"].strip().lower() == "true" if "allow_delete" in values else False
    values["automation_continue"] = "true" if AUTOMATION_CONTINUE_RE.search(response) else "false"
    raw_patch = response.split(PATCH_BEGIN, 1)[1].split(PATCH_END, 1)[0]
    patch = normalize_patch(raw_patch)
    values["automation_continue"] = "true" if re.search(
        r"^PASI_AUTOMATION_CONTINUE:\s*true$",
        response,
        re.MULTILINE | re.IGNORECASE,
    ) else "false"
    return status, summary, next_task, patch, allow_delete, values



def completion_contract(status: str, values: dict[str, str]) -> bool:
    return (
        status == "complete"
        and values.get("requirements", "").lower() == "complete"
        and values.get("limitations", "").lower() in {"handled", "none", "not_applicable"}
        and values.get("research", "").lower() in {"performed", "not_applicable"}
        and values.get("ux", "").lower() in {"verified", "not_applicable"}
        and values.get("backend", "").lower() in {"verified", "not_applicable"}
        and bool(values.get("evidence", "").strip())
    )



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
        completion_contract(status, values) and repository_worktree_is_clean(worktree)
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
- IF the CURRENT TASK is already satisfied by verified repository changes and evidence, THEN do not re-implement it or make cosmetic duplicates; immediately work on the next incomplete roadmap item and return the required completion contract and a concrete next task.
- Inspect the current repository state before editing; do not assume a prior attempt succeeded.
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
    # The executor response is intentionally not authoritative about sequencing.
    del suggested
    decision = select_planner_task(state, phase=state.phase)
    if decision.selected is not None:
        state.current_task_id = decision.selected.id
        return decision.selected.execution_text()

    # Compatibility fallback for legacy/custom runs with no usable roadmap
    # entry. This path is deterministic and ignores model-supplied next-task data.
    candidates = AUTOMATION_TASKS if state.phase == "automation" else ENGINEERING_TASKS
    completed = completed_task_keys()
    current_key = task_key(state.current_task)
    configured = {task_key(item): (index, item) for index, item in enumerate(candidates)}
    current_entry = configured.get(current_key)
    start_index = current_entry[0] + 1 if current_entry and current_key in completed else 0
    ordered = list(candidates[start_index:]) + list(candidates[:start_index])
    for configured_task in ordered:
        if task_key(configured_task) not in completed:
            state.current_task_id = ""
            return configured_task
    state.current_task_id = ""
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
        code, output = command([sys.executable, "-m", "py_compile", *python_files], worktree, 120.0)
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
            [sys.executable, "-c", "import json,sys; json.load(open(sys.argv[1], encoding='utf-8'))", path],
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
            [sys.executable, "-m", "pytest", "-q", *sorted(python_tests)],
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


def verify_and_commit(
    worktree: Path,
    branch: str,
    task: str,
    patch: str,
    allow_delete: bool,
    *,
    push: bool,
    task_number: int | None = None,
    attempt: int | None = None,
    promote: bool = True,
) -> tuple[str, str]:
    validate_patch_paths(patch, allow_delete, worktree)
    gate_mode = os.environ.get("PASI_LOCAL_GATE_MODE", "full").strip().lower() or "full"
    verify_started_at = now_utc().isoformat()
    log_event(
        "verify_started",
        task=task,
        gate_mode=gate_mode,
        started_at=verify_started_at,
    )
    with StageTimer(
        log_event,
        "gate",
        tier=0,
        task_id=task_key(task),
        task_number=task_number,
        attempt=attempt,
        gate="git_apply_check",
    ) as timer:
        code, output = command(
            ["git", "apply", "--check", "--whitespace=nowarn"],
            worktree,
            60.0,
            input_text=patch,
        )
        if code != 0:
            timer.result = "fail"
            timer.classification = classify_failure("git_apply_check", code, output)
            raise RuntimeError(f"git apply --check failed:\n{output}")
    code, output = command(
        ["git", "apply", "--whitespace=nowarn"],
        worktree,
        60.0,
        input_text=patch,
    )
    if code != 0:
        raise RuntimeError(f"git apply failed:\n{output}")
    gate_name = "fast_local" if gate_mode == "fast" else "check_all"
    with StageTimer(
        log_event,
        "gate",
        tier=1,
        task_id=task_key(task),
        task_number=task_number,
        attempt=attempt,
        gate=gate_name,
    ) as timer:
        try:
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
        except Exception as exc:
            timer.result = "fail"
            timer.classification = classify_failure("gate", 1, str(exc))
            raise
    if gate_mode == "fast":
        gate_match = re.search(r"changed=(\d+) files$", output)
        changed_file_count = int(gate_match.group(1)) if gate_match else 0
        if changed_file_count <= 0:
            raise RuntimeError("fast local gate passed without a reported changed-file count")
    else:
        code, status = command(["git", "status", "--porcelain"], worktree, 30.0)
        if code != 0 or not status:
            raise RuntimeError("verification passed but no repository changes remain")
        changed_file_count = len([line for line in status.splitlines() if line.strip()])
    log_event(
        "verify_finished",
        task=task,
        gate_mode=gate_mode,
        finished_at=now_utc().isoformat(),
        changed_files=changed_file_count,
    )
    commit = commit_and_push(worktree, branch, task, push)
    code, status = command(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        worktree,
        30.0,
    )
    if code != 0:
        raise RuntimeError(f"post-commit hygiene check failed: {status}")
    if status.strip():
        raise RuntimeError(f"post-commit hygiene check found uncommitted files:\n{status}")
    if push and promote:
        promotion = command(
            [
                sys.executable,
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
        if reconcile_committed_task(state):
            failure = ""
            continue
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
                engineering_decision = select_planner_task(state, phase="engineering_os")
                if engineering_decision.selected is None:
                    state.stop_reason = "roadmap has no eligible engineering task after automation gate"
                    save_state(state)
                    return
                state.current_task = engineering_decision.selected.execution_text()
                state.current_task_id = engineering_decision.selected.id
                save_state(state)
                continue

        if state.task_retry_cycle == 0:
            state.task_number += 1
        finished = False
        attempt = 1
        while attempt <= MAX_ATTEMPTS:
            if STOP or now_utc() >= datetime.fromisoformat(state.deadline_at):
                return
            state.current_attempt = attempt
            save_state(state)
            log_event("task_attempt_started", phase=state.phase, task_number=state.task_number, attempt=attempt, task=state.current_task)
            log_event(
                "prompt_dispatch_started",
                task_id=task_key(state.current_task),
                task_number=state.task_number,
                attempt=attempt,
                mode=state.phase,
                queue_file_bytes=queue_file_bytes(),
            )
            code, response = invoke_chat(state.current_task, state, failure)
            provider_source = state.last_provider
            emit_operation_metrics(state.current_task, attempt, response)
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
                log_event(
                    "fallback_provider_route",
                    reason="ChatGPT authentication challenge persisted beyond bounded human-recovery wait",
                    task_number=state.task_number,
                )
                fallback = command(
                    [
                        sys.executable,
                        str(control_script("pasi_provider_router.py")),
                        "--task",
                        build_prompt(state.current_task, state, response),
                        "--repo",
                        state.worktree,
                        "--timeout",
                        "180",
                    ],
                    Path(state.worktree),
                    225.0,
                )
                if fallback[0] == 0 and fallback[1].strip():
                    raw_fallback = fallback[1].strip()
                    lines = raw_fallback.splitlines()
                    marker = lines[0].strip() if lines else ""
                    if not marker.startswith("PASI_FALLBACK_PROVIDER:"):
                        failure = "failure_class=fallback_provenance_missing; provider router did not return a provenance marker"
                        attempt += 1
                        continue
                    provider = marker.split(":", 1)[1].strip()
                    if not provider or len(provider) > 80:
                        failure = "failure_class=fallback_provenance_invalid; provider name was empty or oversized"
                        attempt += 1
                        continue
                    response = "\n".join(lines[1:]).lstrip()
                    if not response.strip():
                        failure = "failure_class=fallback_empty_response; provider router returned no response body"
                        attempt += 1
                        continue
                    state.last_provider = f"fallback:{provider}"
                    state.fallback_router_disabled_until = ""
                    save_state(state)
                    code = 0
                else:
                    fallback_output = fallback[1]
                    disable_fallback_router(
                        state,
                        fallback_output or "fallback router returned no usable response",
                    )
                    failure = sanitize_failure_evidence(code, response) + "\n\n[PASI FALLBACK ROUTER]\n" + fallback_output
                    attempt += 1
                    continue
            elif condition in {"provider_usage_limit", "runtime_guard"}:
                if condition == "provider_usage_limit":
                    state.provider_limit_pauses += 1
                    if state.provider_limit_pauses > MAX_PROVIDER_LIMIT_PAUSES:
                        failure = response[-12_000:] or "provider usage limit persisted across bounded pauses"
                        log_event(
                            "provider_pause_budget_exhausted",
                            task_number=state.task_number,
                            count=state.provider_limit_pauses,
                            action="cooldown_and_retry_same_task",
                            cooldown_seconds=PROVIDER_LIMIT_EXHAUSTED_COOLDOWN_SECONDS,
                        )
                        state.provider_limit_pauses = 0
                        save_state(state)
                        if not sleep_until_retry(
                            state,
                            PROVIDER_LIMIT_EXHAUSTED_COOLDOWN_SECONDS,
                        ):
                            return
                        continue
                log_event(
                    "failure_classified",
                    task_id=task_key(state.current_task),
                    task_number=state.task_number,
                    attempt=attempt,
                    stage="provider",
                    classification="infra",
                    condition=condition,
                )
                log_event("provider_pause", condition=condition, count=state.provider_limit_pauses)
                if not sleep_until_retry(state, 30.0 if condition == "runtime_guard" else 300.0):
                    return
                failure = response[-12_000:]
                continue

            if code != 0:
                classification = classify_failure("chat", code, response)
                log_event(
                    "failure_classified",
                    task_id=task_key(state.current_task),
                    task_number=state.task_number,
                    attempt=attempt,
                    stage="chat",
                    classification=classification,
                )
                if classification == "infra":
                    failure = "INFRASTRUCTURE FAILURE (NOT EVALUATED): resend the same patch; do not modify it.\n" + (response[-12_000:] or "ChatGPT/controller infrastructure failed.")
                elif classification == "not_evaluated":
                    failure = "RESULT NOT EVALUATED: evidence is ambiguous or infrastructure-related; do not invent a code repair.\n" + (response[-12_000:] or "No reliable evaluation evidence was produced.")
                else:
                    failure = response[-12_000:] or "ChatGPT returned a code/protocol failure."
                attempt += 1
                continue
            status, summary, next_task, patch, allow_delete, values = parse_response(response)
            contract_ok = completion_contract(status, values)
            log_event(
                "task_response_evidence",
                phase=state.phase,
                task_id=task_key(state.current_task),
                task_number=state.task_number,
                attempt=attempt,
                provider=provider_source,
                status=status,
                contract_ok=contract_ok,
                response_chars=len(response),
                summary_chars=len(summary),
                evidence_chars=len(values.get("evidence", "")),
                patch_chars=len(patch),
                next_task_chars=len(next_task),
            )
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
                    evidence=(f"provider={provider_source}\n" + evidence_text).strip(),
                    phase=state.phase,
                    automation_continue=values.get("automation_continue", "").lower() == "true",
                    task_id=state.current_task_id,
                )
                state.last_result = evidence_text
                state.next_task = choose_next_task(state, next_task)
                state.recent_tasks.append(state.current_task)
                state.current_task = state.next_task
                state.next_task = ""
                state.current_attempt = 0
                state.task_retry_cycle = 0
                state.last_failure_signature = ""
                state.same_failure_cycles = 0
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
                attempt += 1
                continue
            try:
                commit, verification = verify_and_commit(
                    Path(state.worktree),
                    state.branch,
                    state.current_task,
                    patch,
                    allow_delete,
                    push=push,
                    task_number=state.task_number,
                    attempt=attempt,
                    promote=provider_source == "chatgpt_browser",
                )
            except Exception as exc:
                failure = str(exc)
                classification = classify_failure("verification", 1, failure)
                log_event(
                    "failure_classified",
                    task_id=task_key(state.current_task),
                    task_number=state.task_number,
                    attempt=attempt,
                    stage="verification",
                    classification=classification,
                )
                log_event("verification_failed", task_number=state.task_number, attempt=attempt, error=failure[-6000:], classification=classification)
                command(["git", "reset", "--hard", "HEAD"], Path(state.worktree), 60.0)
                command(["git", "clean", "-fd"], Path(state.worktree), 60.0)
                attempt += 1
                continue
            state.completed_tasks += 1
            if state.phase == "automation":
                state.automation_tasks_since_gate += 1
            record_task_ledger(
                state.current_task,
                "completed",
                commit=commit,
                evidence=(f"provider={provider_source}\n" + (summary or verification[-3000:])).strip(),
                phase=state.phase,
                automation_continue=values.get("automation_continue", "").lower() == "true",
                task_id=state.current_task_id,
            )
            state.last_result = summary or verification[-3000:]
            state.next_task = next_task.strip()
            state.recent_tasks.append(state.current_task)
            state.current_task = choose_next_task(state, state.next_task)
            state.next_task = ""
            state.current_attempt = 0
            state.task_retry_cycle = 0
            state.last_failure_signature = ""
            state.same_failure_cycles = 0
            save_state(state)
            log_event("task_completed", phase=state.phase, task_number=state.task_number, commit=commit, summary=summary[-2000:])
            failure = ""
            finished = True
            break
        if not finished:
            failed_task = state.current_task
            state.failed_tasks += 1
            state.last_result = failure or "bounded retry cycle exhausted"
            normalized_failure = re.sub(r"\s+", " ", state.last_result).strip()
            failure_signature = hashlib.sha256(normalized_failure[:12000].encode("utf-8")).hexdigest()
            if failure_signature == state.last_failure_signature:
                state.same_failure_cycles += 1
            else:
                state.same_failure_cycles = 1
            state.last_failure_signature = failure_signature
            state.task_retry_cycle += 1
            state.recent_tasks = state.recent_tasks[-12:]
            state.current_attempt = 0
            save_state(state)
            log_event(
                "task_retry_cycle_exhausted",
                phase=state.phase,
                task_number=state.task_number,
                failed_task=failed_task,
                retry_cycle=state.task_retry_cycle,
                same_failure_cycles=state.same_failure_cycles,
                error=state.last_result[-6000:],
                action="retain_current_task",
            )
            failure = (
                f"RETRY CYCLE {state.task_retry_cycle} EXHAUSTED FOR CURRENT TASK. "
                "Do not advance to another task. Re-inspect the repository, use the failure evidence, "
                "and change the implementation strategy before another bounded retry cycle.\n"
                + state.last_result
            )


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
    parser.add_argument("--roadmap", type=Path, default=None)
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
            if not state.roadmap_path.strip():
                state.roadmap_path = str(planner_roadmap_path(explicit=args.roadmap))
            state.stop_reason = ""
            resume = True
            log_event("run_resumed", **state.to_dict())
        else:
            started = now_utc()
            run_id = f"overnight-{uuid.uuid4().hex}"
            selected_roadmap = planner_roadmap_path(explicit=args.roadmap)
            hybrid_planner.load_roadmap_with_overlay(selected_roadmap, ROADMAP_OVERLAY_PATH)
            selected_task, guard_applied, prior_repeats = choose_run_start_task(
                "automation", args.task.strip(), run_id, selected_roadmap
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
                roadmap_path=str(selected_roadmap),
                current_task_id=task_id_for_prompt(
                    hybrid_planner.load_roadmap_with_overlay(selected_roadmap, ROADMAP_OVERLAY_PATH),
                    selected_task,
                ),
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

        actual_worktree = ensure_worktree(Path(state.worktree), state.branch, resume=resume)
        actual_worktree_text = str(actual_worktree)
        if state.worktree != actual_worktree_text:
            state.worktree = actual_worktree_text
            save_state(state)
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
