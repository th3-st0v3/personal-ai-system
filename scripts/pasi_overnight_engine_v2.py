from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import signal
import shutil
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

from scripts.pasi_timeout_policy import load_timeout_policy

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = REPO_ROOT / ".runtime" / "overnight"
STATE_PATH = RUNTIME_DIR / "state.json"
EVENT_LOG = RUNTIME_DIR / "events.jsonl"
PID_PATH = RUNTIME_DIR / "runner.pid"
ROADMAP_LOOP_GUARD_PATH = RUNTIME_DIR / "roadmap-loop-guard.json"
BRIDGE_URL = "http://127.0.0.1:8765"
CONTROLLER_MANIFEST_PATH = REPO_ROOT / "automation" / "chromium" / "pasi-chatgpt" / "manifest.json"
DEFAULT_WORKTREE = Path.home() / ".pasi-worktrees" / "personal-ai-system-overnight"
DEFAULT_HOURS = 10.0
MIN_HOURS = 8.0
MAX_HOURS = float("inf")
BRIDGE_HEALTH = "http://127.0.0.1:8765/health"
MAX_PATCH_BYTES = 250_000
MAX_OUTPUT_CHARS = 20_000
MAX_ATTEMPTS = 3
PROTECTED_UNATTENDED_PATHS = frozenset({
    "scripts/check_all.sh",
    "scripts/pasi_overnight_hardening.py",
    "scripts/pasi_overnight_engine_v2.py",
    "automation/chromium/pasi-chatgpt/manifest.json",
})
PROTECTED_UNATTENDED_PREFIXES = (
    ".github/",
    ".githooks/",
    "hooks/",
)
TIMEOUT_POLICY = load_timeout_policy()
TASK_TIMEOUT_SECONDS = TIMEOUT_POLICY["python_wait_seconds"]
WATCHDOG_MAX_AGE_SECONDS = TIMEOUT_POLICY["stale_seconds"]
STANDBY_SECONDS = 30.0
AUTOMATION_TASKS_PER_GATE = 2
MAX_PROVIDER_LIMIT_PAUSES = 3
ROADMAP_CONSECUTIVE_RUN_LIMIT = 2
ROADMAP_LOOP_GUARD_HISTORY_LIMIT = 24
TASK_LEDGER_PATH = RUNTIME_DIR / "task-ledger.json"
MAX_TASK_TEXT_CHARS = 4000

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
    "allow_delete": re.compile(r"^PASI_RESULT_ALLOW_DELETE:\s*(true|false)$", re.MULTILINE | re.IGNORECASE),
}
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


def task_key(task: str) -> str:
    return hashlib.sha256(task.strip().encode("utf-8")).hexdigest()


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
    payload = {
        "schema_version": 1,
        "tasks": {str(key): dict(value) for key, value in ledger.items()},
    }
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
    key = task_key(normalized)
    ledger[key] = {
        "task": normalized,
        "status": status,
        "commit": commit or "",
        "evidence": evidence[-4000:],
        "phase": phase,
        "automation_continue": automation_continue,
        "updated_at": now_utc().isoformat(),
    }
    save_task_ledger(ledger)


def completed_task_keys() -> set[str]:
    return {
        key
        for key, value in load_task_ledger().items()
        if str(value.get("status", "")).casefold() == "completed"
    }


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
    if len(patch.encode("utf-8")) > MAX_PATCH_BYTES:
        raise ValueError("model patch exceeds configured size bound")
    if any(marker in patch for marker in ("new file mode 120000", "new file mode 160000", "new mode 120000", "new mode 160000")):
        raise ValueError("symlink and submodule additions are not allowed in unattended patches")
    matches = re.findall(r"^diff --git a/(.+) b/(.+)$", patch, re.MULTILINE)
    sections = re.split(r"(?m)^diff --git ", patch)[1:]
    deleted_paths: set[str] = set()
    for section in sections:
        if re.search(r"(?m)^\\+\\+\\+ /dev/null$", section):
            header = section.splitlines()[0] if section.splitlines() else ""
            header_match = re.match(r"a/(\\S+) b/(\\S+)$", header)
            if header_match:
                deleted_paths.add(header_match.group(2))
    if deleted_paths and not allow_delete:
        raise ValueError("file deletion requires PASI_RESULT_ALLOW_DELETE: true: " + ", ".join(sorted(deleted_paths)[:10]))

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
            if normalized in PROTECTED_UNATTENDED_PATHS or any(normalized.startswith(prefix) for prefix in PROTECTED_UNATTENDED_PREFIXES):
                raise ValueError(f"protected unattended patch path requires human-approved branch: {path_value}")
            if worktree is not None:
                ignored = subprocess.run(
                    ["git", "-C", str(worktree), "check-ignore", "-q", "--", normalized],
                    capture_output=True,
                    check=False,
                )
                if ignored.returncode == 0:
                    raise ValueError(f"patch path is Git-ignored and outside the tracked change boundary: {path_value}")
        if new_path == "/dev/null" and not allow_delete:
            raise ValueError("file deletion requires PASI_RESULT_ALLOW_DELETE: true")


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


def command(
    command: list[str],
    cwd: Path,
    timeout: float,
    *,
    input: str | None = None,
) -> tuple[int, str]:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            input=input,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)
    output = ((result.stdout or "") + (result.stderr or "")).strip()
    return result.returncode, output[-20_000:]


def repository_worktree_is_clean(worktree: Path) -> bool:
    code, status = command(["git", "status", "--porcelain", "--untracked-files=all"], worktree, 30.0)
    return code == 0 and not status.strip()


def run_validation_sandbox(worktree: Path, timeout: float = 900.0) -> str:
    """Run canonical validation from an isolated filesystem/network view."""
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
            # --numstat -z emits a second NUL-delimited pathname for rename
            # records. Treat it as another resolved path rather than rejecting
            # a legitimate rename outright.
            fields.append(token)

    for path_value in fields:
        if not path_value or path_value == "/dev/null":
            continue
        candidate = (root / path_value).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise RuntimeError(f"git apply resolved an unsafe path: {path_value}") from exc
        if path_value in PROTECTED_UNATTENDED_PATHS or any(path_value.startswith(prefix) for prefix in PROTECTED_UNATTENDED_PREFIXES):
            raise RuntimeError(f"git apply resolved a protected unattended path: {path_value}")


def apply_patch(worktree: Path, patch: str, allow_delete: bool) -> str:
    validate_patch_paths(patch, allow_delete, worktree)
    code, summary = command(["git", "apply", "--numstat", "-z", "-"], worktree, 60.0, input=patch)
    if code != 0:
        raise RuntimeError(f"git apply path resolution failed:\n{summary}")
    validate_git_resolved_paths(worktree, summary)
    code, output = command(["git", "apply", "--check", "--whitespace=nowarn", "-"], worktree, 60.0, input=patch)
    if code != 0:
        raise RuntimeError(f"git apply --check failed:\n{output}")
    code, output = command(["git", "apply", "--whitespace=nowarn", "-"], worktree, 60.0, input=patch)
    if code != 0:
        raise RuntimeError(f"git apply failed:\n{output}")
    return output


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


def no_change_completion_is_satisfied(
    worktree: Path,
    status: str,
    next_task: str,
    patch: str,
    values: dict[str, str],
) -> bool:
    return (
        completion_contract(status, values)
        and not patch
        and values.get("repository_progress", "").lower() == "stopped"
        and bool(next_task.strip())
        and repository_worktree_is_clean(worktree)
    )

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
    raise RuntimeError("local PASI bridge did not become healthy")


def worktree_start_ref() -> str:
    configured = os.environ.get("PASI_OVERNIGHT_BASE_REF", "").strip()
    return configured or "HEAD"


def ensure_worktree(path: Path, branch: str, *, resume: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not (path / ".git").exists():
        code, output = command(
            ["git", "worktree", "add", "-B", branch, str(path), worktree_start_ref()],
            REPO_ROOT,
            60.0,
        )
        if code != 0:
            raise RuntimeError(f"could not create overnight worktree: {output}")
        log_event("worktree_created", branch=branch, base_ref=worktree_start_ref(), path=str(path))
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
        f"{BRIDGE_URL}/browser/health",
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
    native_controller = data.get("native_controller")
    return (
        isinstance(expected, str)
        and expected == actual
        and native_controller is True
    )


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
    # Do not feed raw provider/browser output back into the next model prompt.
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
    automation_entries = [
        value for value in ledger.values()
        if isinstance(value, dict) and value.get("phase") == "automation" and value.get("status") == "completed"
    ]
    automation_entries.sort(key=lambda value: str(value.get("updated_at", "")))
    recent = automation_entries[-AUTOMATION_TASKS_PER_GATE:]
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
        "automation_evidence": "Recent automation tasks have verified evidence recorded in the durable task ledger.",
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
    code, output = command(
        [sys.executable, "scripts/pasi_chat_guard.py", prompt, "--github", "public", "--timeout", str(TASK_TIMEOUT_SECONDS)],
        Path(state.worktree),
        TASK_TIMEOUT_SECONDS + 45.0,
    )
    if provider_condition(code, output) is None:
        return code, output
    if os.environ.get("PASI_PRIMARY_CHATGPT_ONLY", "").strip().casefold() in {"1", "true", "yes"}:
        return code, sanitize_failure_evidence(code, output)
    fallback = command(
        [sys.executable, "scripts/pasi_provider_router.py", "--task", prompt, "--repo", str(state.worktree), "--timeout", "180"],
        Path(state.worktree),
        225.0,
    )
    if fallback[0] == 0 and fallback[1].strip():
        return 0, fallback[1]
    return code, sanitize_failure_evidence(code, output) + " | fallback=" + sanitize_failure_evidence(fallback[0], fallback[1])


def parse_response(response: str) -> tuple[str, str, str, str, bool, dict[str, str]]:
    if not isinstance(response, str):
        raise ValueError("model response must be text")
    values: dict[str, str] = {}
    missing_or_duplicate: list[str] = []
    for key, pattern in MARKERS.items():
        matches = pattern.findall(response)
        if len(matches) != 1:
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


def continuation_directive(state: OvernightState, _task: str | None = None) -> str:
    candidates = AUTOMATION_TASKS if state.phase == "automation" else ENGINEERING_TASKS
    roadmap = "\n".join(f"- {item}" for item in candidates)
    recent = "\n".join(f"- {item}" for item in state.recent_tasks[-12:]) or "- none recorded"
    return f"""TASK CONTINUATION:
- Inspect the current repository state and recent commits before deciding whether the CURRENT TASK is still incomplete.
- Keep working on the CURRENT TASK until the requirement is implemented, tested, diagnosed, and verified.
- IF the CURRENT TASK is already satisfied by verified repository changes and evidence, THEN do not re-implement it, do not make cosmetic duplicate changes, and do not ask the human what to do next; immediately work on the next incomplete roadmap item below.
- IF the CURRENT TASK is not yet satisfied, THEN continue it.
- If the same failure repeats, change approach instead of repeating the failed path; use PREVIOUS FAILURE EVIDENCE to guide the different approach.
- A response-repair prompt repairs the response contract; it does not restart an implementation that is already verified.
- After a verified completion, set PASI_RESULT_NEXT_TASK to the next incomplete, high-value item rather than repeating CURRENT TASK; immediately continue to the next incomplete roadmap task.
- IF the CURRENT TASK is already satisfied and another implementation pass would make no repository changes, THEN report PASI_RESULT_REPOSITORY_PROGRESS: stopped with an empty patch and immediately advance to PASI_RESULT_NEXT_TASK; never invent a cosmetic patch just to keep the task alive.
- IF the CURRENT TASK still has a concrete repository change to make, THEN report PASI_RESULT_REPOSITORY_PROGRESS: changed and provide the required patch.
- If the verified evidence shows another automation, computer-use, recovery, integration, or security capability is materially necessary to satisfy the objective, include exactly PASI_AUTOMATION_CONTINUE: true. Otherwise omit that line.
- do not invent work or cosmetic changes; report stopped only when the task is satisfied and no concrete repository change remains.
- Preserve all authentication, authorization, approval, path, network, and verification boundaries. Pause for human input only when an explicit approval boundary requires it.
ROADMAP PHASE: {state.phase}
ROADMAP:
{roadmap}
RECENT TASKS:
{recent}"""

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
- Local Ollama/OpenCode are permitted fallback evidence/model sources when ChatGPT is unavailable. OpenRouter/Perplexity remote APIs receive repository context only when PASI_ALLOW_REMOTE_CODE=1 is explicitly set.

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
PASI_RESULT_REPOSITORY_PROGRESS: changed|stopped
PASI_RESULT_ALLOW_DELETE: true|false
PASI_AUTOMATION_CONTINUE: true   # optional; include only when another automation capability is materially necessary
PASI_RESULT_PATCH_BEGIN
<one unified git diff>
PASI_RESULT_PATCH_END

The patch must apply with git apply, modify only repository files, and contain no symlink or submodule additions. Do not use shell commands as the change mechanism.
{previous}"""


def choose_next_task(state: OvernightState, suggested: str) -> str:
    candidates = AUTOMATION_TASKS if state.phase == "automation" else ENGINEERING_TASKS
    completed = completed_task_keys()
    validated_suggestion = valid_next_task(suggested, state.current_task, state.recent_tasks)
    if validated_suggestion:
        return validated_suggestion
    normalized_suggestion = re.sub(r"\s+", " ", suggested).strip()
    current_key = task_key(state.current_task)
    configured = {task_key(item): (index, item) for index, item in enumerate(candidates)}
    suggestion_key = task_key(normalized_suggestion) if normalized_suggestion else ""
    current_entry = configured.get(current_key)
    suggestion_entry = configured.get(suggestion_key)

    if suggestion_entry and suggestion_key not in completed and suggestion_key != current_key:
        return suggestion_entry[1]

    advance_from_key: str | None = None
    if suggestion_entry and (suggestion_key == current_key or suggestion_key in completed):
        advance_from_key = suggestion_key
    elif not normalized_suggestion:
        recent = {task_key(item) for item in state.recent_tasks[-12:]}
        if current_key in completed or current_key in recent:
            advance_from_key = current_key
        elif current_entry and current_key not in completed:
            return current_entry[1]
    elif current_entry and current_key not in completed:
        completed_indices = [
            index for key, (index, _item) in configured.items() if key in completed
        ]
        later_completed = [index for index in completed_indices if index > current_entry[0]]
        if later_completed:
            advance_from_key = task_key(candidates[max(later_completed)])
        else:
            # An invented/non-roadmap suggestion cannot replace an unfinished task.
            return current_entry[1]

    start_index = configured[advance_from_key][0] + 1 if advance_from_key in configured else 0
    ordered = list(candidates[start_index:]) + list(candidates[:start_index])
    for configured_task in ordered:
        if task_key(configured_task) not in completed:
            return configured_task
    return choose_unique(candidates, state)


def verify_and_commit(worktree: Path, branch: str, task: str, patch: str, allow_delete: bool, *, push: bool) -> tuple[str, str]:
    output = apply_patch(worktree, patch, allow_delete)
    validation_output = run_validation_sandbox(worktree)
    code, status = command(["git", "status", "--porcelain"], worktree, 30.0)
    if code != 0 or not status:
        raise RuntimeError("verification passed but no repository changes remain")
    output = output + ("\n" if output else "") + validation_output
    commit = commit_and_push(worktree, branch, task, push)
    if push:
        promotion = command(
            [
                sys.executable,
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
        try:
            ensure_services()
        except Exception as exc:
            log_event("service_recovery_failed", error=str(exc)[-4000:])

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
            log_event("standby_started", reason="browser controller/extension heartbeat is stale; waiting for browser recovery while keeping local services healthy")
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
                fallback_failure = sanitize_failure_evidence(code, response)
                fallback = command(
                    [
                        sys.executable,
                        "scripts/pasi_provider_router.py",
                        "--task",
                        build_prompt(state.current_task, state, fallback_failure),
                        "--repo",
                        state.worktree,
                        "--timeout",
                        "180",
                    ],
                    Path(state.worktree),
                    225.0,
                )
                if fallback[0] == 0:
                    response = fallback[1]
                    code = 0
            elif condition in {"provider_usage_limit", "runtime_guard"}:
                if condition == "provider_usage_limit":
                    state.provider_limit_pauses += 1
                    if state.provider_limit_pauses > MAX_PROVIDER_LIMIT_PAUSES:
                        failure = sanitize_failure_evidence(code, response) or "failure_class=provider_usage_limit"
                        log_event("provider_pause_budget_exhausted", task_number=state.task_number, count=state.provider_limit_pauses)
                        break
                log_event("provider_pause", condition=condition, count=state.provider_limit_pauses)
                if not sleep_until_retry(state, 30.0 if condition == "runtime_guard" else 300.0):
                    return
                failure = sanitize_failure_evidence(code, response)
                continue

            if code != 0:
                failure = sanitize_failure_evidence(code, response)
                continue
            status, summary, next_task, patch, allow_delete, values = parse_response(response)
            contract_ok = completion_contract(status, values)
            if contract_ok and no_change_completion_is_satisfied(
                Path(state.worktree), status, next_task, patch, values
            ):
                state.completed_tasks += 1
                record_task_ledger(
                    state.current_task,
                    "completed",
                    evidence=values.get("evidence", ""),
                    phase=state.phase,
                    automation_continue=values.get("automation_continue", "").lower() == "true",
                )
                state.last_result = summary or values.get("evidence", "validated task already satisfied; no repository change remained")
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
                failure = f"failure_class=contract_error; summary={re.sub(r'\s+', ' ', summary).strip()[:800]}" if summary else "failure_class=contract_error; provider returned no usable completion contract"
                continue
            try:
                commit, verification = verify_and_commit(Path(state.worktree), state.branch, state.current_task, patch, allow_delete, push=push)
            except Exception as exc:
                failure = sanitize_failure_evidence(1, str(exc))
                log_event("verification_failed", task_number=state.task_number, attempt=attempt, error=failure[-6000:])
                command(["git", "reset", "--hard", "HEAD"], Path(state.worktree), 60.0)
                command(["git", "clean", "-fd"], Path(state.worktree), 60.0)
                continue
            state.completed_tasks += 1
            record_task_ledger(
                state.current_task,
                "completed",
                commit=commit,
                evidence=(summary + "\n" + verification).strip(),
                phase=state.phase,
                automation_continue=values.get("automation_continue", "").lower() == "true",
            )
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
    if not math.isfinite(args.hours) or args.hours < MIN_HOURS:
        parser.error(f"--hours must be a finite value >= {MIN_HOURS:g}")

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)
    acquire_lock()
    children: list[subprocess.Popen[bytes]] = []
    state: OvernightState | None = None
    try:
        code, output = command(["git", "fetch", "origin", "main"], REPO_ROOT, 120.0)
        if code != 0:
            # The unattended runner may start from an already-verified feature
            # branch while offline. Remote refresh is useful but is not a startup
            # prerequisite; local HEAD remains the authoritative worktree base.
            log_event("git_fetch_deferred", remote="origin/main", error=sanitize_failure_evidence(code, output))
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
