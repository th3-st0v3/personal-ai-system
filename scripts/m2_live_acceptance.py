#!/usr/bin/env python3
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
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.pasi_desktop_preflight import (
    expected_controller_version,
    expected_extension_manifest_version,
    heartbeat_age_seconds,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
BRIDGE_URL = "http://127.0.0.1:8765"
TOKEN_FILE = Path.home() / ".pasi" / "bridge-token"
QUEUE_PATH = REPO_ROOT / ".ai" / "queue.json"
ARTIFACT_DIR = REPO_ROOT / ".runtime" / "acceptance"
DEFAULT_RUNTIME_BASE_DIR = Path.home() / ".pasi" / "m2-acceptance"
CHAT_URL_RE = re.compile(r"^https://chatgpt\.com/c/")
PROMPT_OP_RE = re.compile(r"Prompt operation:\s*([A-Za-z0-9._:-]+)")
RESUME_OP_RE = re.compile(r"Resuming persisted ChatGPT operation:\s*([A-Za-z0-9._:-]+)")
RETRY_OP_RE = re.compile(r"Retry prompt operation:\s*([A-Za-z0-9._:-]+)")
RUNNER_LOG_FILENAME = "runner.log"
BROWSER_MAX_HEARTBEAT_AGE_SECONDS = 30.0
OPERATION_QUEUE_TIMEOUT_SECONDS = 360.0
OPERATION_POLL_SECONDS = 0.2


class M2AcceptanceError(RuntimeError):
    def __init__(self, stage: str, message: str) -> None:
        super().__init__(message)
        self.stage = stage


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_signature(value: object) -> tuple[int, int, str] | None:
    if not isinstance(value, str):
        return None
    parts = value.split(":", 2)
    if len(parts) != 3 or not parts[0].isdigit() or not parts[1].isdigit():
        return None
    user_count, assistant_count = int(parts[0]), int(parts[1])
    fingerprint = parts[2]
    if not fingerprint and (user_count or assistant_count):
        return None
    return user_count, assistant_count, fingerprint


def validate_signature_progression(before: object, after: object) -> None:
    prev = parse_signature(before)
    curr = parse_signature(after)
    if prev is None or curr is None:
        raise ValueError("invalid M2 conversation signature")
    if curr[:2] != (prev[0] + 1, prev[1] + 1):
        raise ValueError(
            f"expected +1/+1 conversation signature from {prev[:2]}, got {curr[:2]}"
        )
    if not curr[2] or curr[2] == prev[2]:
        raise ValueError("M2 final conversation fingerprint did not change")


def token() -> str:
    try:
        value = TOKEN_FILE.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise M2AcceptanceError("preflight", f"bridge token unavailable: {exc}") from exc
    if not value:
        raise M2AcceptanceError("preflight", "bridge token is empty")
    return value


def request_json(path: str, method: str = "GET", payload: object | None = None) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {token()}"}
    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(BRIDGE_URL + path, headers=headers, data=body, method=method)
    try:
        with urllib.request.urlopen(request, timeout=6) as response:
            value = json.loads(response.read(2_000_000).decode("utf-8"))
    except (OSError, urllib.error.URLError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise M2AcceptanceError("bridge", f"{method} {path} failed: {exc}") from exc
    if not isinstance(value, dict):
        raise M2AcceptanceError("bridge", f"{method} {path} returned a non-object")
    return value


def observation(path: str) -> dict[str, Any]:
    payload = request_json(path)
    value = payload.get("observation")
    if not isinstance(value, dict):
        raise M2AcceptanceError("browser", f"{path} did not return an observation")
    data = value.get("data")
    if not isinstance(data, dict):
        return value
    normalized = dict(data)
    for key in ("captured_at", "schema_version"):
        if key not in normalized and key in value:
            normalized[key] = value[key]
    return normalized


def browser_health() -> dict[str, Any]:
    return observation("/browser/health")


def browser_response() -> dict[str, Any]:
    return observation("/browser/response")


def operation(operation_id: str) -> dict[str, Any]:
    encoded = urllib.parse.quote(operation_id, safe="")
    value = request_json(f"/operation?operation_id={encoded}").get("operation")
    if not isinstance(value, dict):
        raise M2AcceptanceError("operation", f"operation {operation_id} unavailable")
    return value


def queue_items() -> list[dict[str, Any]]:
    try:
        value = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise M2AcceptanceError("operation", f"cannot read {QUEUE_PATH}: {exc}") from exc
    if not isinstance(value, list):
        raise M2AcceptanceError("operation", "queue is not a list")
    return [item for item in value if isinstance(item, dict)]


def find_operation(marker: str) -> str | None:
    for item in queue_items():
        if marker in str(item.get("prompt") or ""):
            value = item.get("operation_id")
            if isinstance(value, str) and value.strip():
                return value
    return None


def queue_operation_ids(marker: str) -> list[str]:
    values: list[str] = []
    for item in queue_items():
        if marker not in str(item.get("prompt") or ""):
            continue
        value = item.get("operation_id")
        if not isinstance(value, str) or not value.strip():
            continue
        operation_id = value.strip()
        if operation_id not in values:
            values.append(operation_id)
    return values


def read_pid(runtime_dir: Path, name: str) -> int | None:
    try:
        value = int((runtime_dir / name).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    return value if value > 1 else None


def process_exists(pid: int | None) -> bool:
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def process_command(pid: int) -> str:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return ""
    return raw.replace(b"\x00", b" ").decode("utf-8", "ignore")


def process_cwd(pid: int) -> str:
    try:
        return os.readlink(f"/proc/{pid}/cwd")
    except OSError:
        return ""


def process_parent(pid: int) -> int | None:
    try:
        completed = subprocess.run(
            ["ps", "-o", "ppid=", "-p", str(pid)],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    try:
        parent = int(completed.stdout.strip())
    except ValueError:
        return None
    return parent if parent > 1 else None


def listening_pids(port: int = 8765) -> list[int]:
    commands = [
        ["ss", "-ltnp", f"sport = :{port}"],
        ["ss", "-ltnp"],
    ]
    for command in commands:
        try:
            completed = subprocess.run(command, capture_output=True, text=True, check=False)
        except OSError:
            continue
        if completed.returncode != 0:
            continue
        if command[-1] == "-ltnp" and f":{port}" not in completed.stdout:
            continue
        pids: list[int] = []
        for match in re.finditer(r"pid=(\d+)", completed.stdout):
            value = int(match.group(1))
            if value not in pids:
                pids.append(value)
        if pids:
            return pids

    # Some WSL/Linux configurations omit process ownership from ss output.
    # Fall back to lsof without weakening the later PASI-process identity check.
    try:
        completed = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return []
    if completed.returncode != 0:
        return []
    pids = []
    for line in completed.stdout.splitlines():
        if line.strip().isdigit():
            value = int(line.strip())
            if value not in pids:
                pids.append(value)
    return pids


def is_managed_bridge_process(command_line: str, cwd: str) -> bool:
    if "automation.orchestrator.bridge" not in command_line:
        return False

    repo = str(REPO_ROOT)
    rooted_in_repo = cwd == repo or cwd.startswith(repo + os.sep) or repo in command_line
    bridge_source_exists = bool(cwd) and (Path(cwd) / "automation" / "orchestrator" / "bridge.py").is_file()

    # Current managed launcher: router owns the bridge child.
    if "pasi_log_router.py" in command_line:
        return rooted_in_repo or bridge_source_exists

    # Direct/legacy managed launcher: accept any PASI checkout/worktree that
    # actually contains the bridge implementation. This covers managed runtime
    # worktrees whose cwd is not the acceptance checkout.
    return rooted_in_repo or bridge_source_exists


def discover_managed_bridge_pid() -> tuple[int, dict[str, Any]] | None:
    for listener_pid in listening_pids():
        current = listener_pid
        visited: set[int] = set()
        direct_candidate: tuple[int, dict[str, Any]] | None = None
        for _ in range(16):
            if current in visited or current <= 1:
                break
            visited.add(current)
            command_line = process_command(current)
            cwd = process_cwd(current)
            if is_managed_bridge_process(command_line, cwd):
                evidence = {
                    "listener_pid": listener_pid,
                    "owner_pid": current,
                    "owner_command_line": command_line,
                    "owner_cwd": cwd,
                    "discovered_at": utc_now(),
                }
                if "pasi_log_router.py" in command_line:
                    return current, evidence
                if direct_candidate is None:
                    direct_candidate = (current, evidence)
            parent = process_parent(current)
            if parent is None:
                break
            current = parent
        if direct_candidate is not None:
            return direct_candidate
    return None


def descendants(pid: int) -> list[int]:
    pending = [pid]
    result: list[int] = []
    while pending:
        parent = pending.pop()
        try:
            completed = subprocess.run(["pgrep", "-P", str(parent)], capture_output=True, text=True, check=False)
        except OSError:
            continue
        for line in completed.stdout.splitlines():
            try:
                child = int(line)
            except ValueError:
                continue
            if child not in result:
                result.append(child)
                pending.append(child)
    return result


def try_kill_managed_tree(
    runtime_dir: Path,
    pid_name: str,
    expected_fragment: str | tuple[str, ...],
) -> dict[str, Any]:
    pid = read_pid(runtime_dir, pid_name)
    if pid is None or not process_exists(pid):
        return {"pid": pid, "skipped": True}
    try:
        return kill_managed_tree(runtime_dir, pid_name, expected_fragment)
    except M2AcceptanceError as exc:
        return {"pid": pid, "skipped": False, "error": str(exc)}


def kill_managed_tree(
    runtime_dir: Path,
    pid_name: str,
    expected_fragment: str | tuple[str, ...],
) -> dict[str, Any]:
    pid = read_pid(runtime_dir, pid_name)
    if pid is None or not process_exists(pid):
        raise M2AcceptanceError("process_kill", f"{pid_name} is not live")
    command_line = process_command(pid)
    expected = (expected_fragment,) if isinstance(expected_fragment, str) else expected_fragment
    if not any(fragment in command_line for fragment in expected):
        raise M2AcceptanceError(
            "process_kill",
            f"{pid_name} PID {pid} is not the expected PASI process: {command_line!r}",
        )
    children = descendants(pid)
    signaled_at = utc_now()
    for child in reversed(children):
        try:
            os.kill(child, signal.SIGTERM)
        except OSError:
            pass
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline and process_exists(pid):
        time.sleep(0.1)
    forced: list[int] = []
    if process_exists(pid):
        for child in reversed(descendants(pid)):
            try:
                os.kill(child, signal.SIGKILL)
                forced.append(child)
            except OSError:
                pass
        try:
            os.kill(pid, signal.SIGKILL)
            forced.append(pid)
        except OSError:
            pass
    return {
        "pid": pid,
        "pid_file": str(runtime_dir / pid_name),
        "command_line": command_line,
        "descendants": children,
        "forced_pids": forced,
        "signaled_at": signaled_at,
    }


def runner_log_path(runtime_dir: Path) -> Path:
    return runtime_dir / RUNNER_LOG_FILENAME


def read_log_since(path: Path, offset: int = 0, max_chars: int = 30_000) -> str:
    try:
        with path.open("rb") as handle:
            handle.seek(max(0, offset))
            payload = handle.read(max(1, max_chars * 4))
    except OSError:
        return ""
    return payload.decode("utf-8", "ignore")[-max_chars:]


def wait_for(predicate, timeout: float, description: str, *, poll_seconds: float = 0.5):
    if poll_seconds <= 0:
        raise ValueError("poll_seconds must be positive")
    deadline = time.monotonic() + timeout
    last: Any = None
    while time.monotonic() < deadline:
        last = predicate()
        if last:
            return last
        time.sleep(poll_seconds)
    raise M2AcceptanceError("wait", f"timed out waiting for {description}; last={last!r}")


def runtime_startup_diagnostics(runtime_dir: Path, max_chars: int = 12000) -> dict[str, Any]:
    diagnostics: dict[str, Any] = {}
    state_path = runtime_dir / "state.json"
    log_path = runner_log_path(runtime_dir)
    try:
        diagnostics["state"] = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        diagnostics["state"] = None
    diagnostics["runner_pid"] = read_pid(runtime_dir, "runner.pid")
    diagnostics["supervisor_pid"] = read_pid(runtime_dir, "supervisor.pid")
    diagnostics["runner_log_tail"] = read_log_since(log_path, 0, max_chars=max_chars)
    return diagnostics


def validate_browser_health(
    data: dict[str, Any],
    expected_controller: str,
    expected_extension: str,
    max_heartbeat_age: float,
    expected_chat_url: str | None = None,
    *,
    require_manual_reload_gate_capability: bool = False,
) -> float:
    if data.get("kind") != "chatgpt_health":
        raise M2AcceptanceError("browser", f"browser health kind is not chatgpt_health: {data.get('kind')!r}")
    if data.get("native_controller") is not True:
        raise M2AcceptanceError("browser", "native PASI Chromium controller is not active")
    if data.get("controller_version") != expected_controller:
        raise M2AcceptanceError(
            "browser",
            f"native PASI controller version mismatch: expected {expected_controller!r}, observed {data.get('controller_version')!r}",
        )
    if data.get("extension_manifest_version") != expected_extension:
        raise M2AcceptanceError(
            "browser",
            "loaded PASI extension is stale or unidentified: "
            f"expected {expected_extension!r}, observed {data.get('extension_manifest_version')!r}",
        )
    if require_manual_reload_gate_capability and data.get("manual_reload_gate_supported") is not True:
        raise M2AcceptanceError(
            "browser",
            "loaded PASI controller does not advertise the M2 manual reload gate capability",
        )
    captured_at = data.get("captured_at")
    if not isinstance(captured_at, str) or not captured_at.strip():
        raise M2AcceptanceError("browser", "browser health is missing captured_at")
    try:
        heartbeat_age = heartbeat_age_seconds(captured_at)
    except RuntimeError as exc:
        raise M2AcceptanceError("browser", str(exc)) from exc
    if heartbeat_age < -5 or heartbeat_age > max_heartbeat_age:
        raise M2AcceptanceError(
            "browser",
            f"browser heartbeat is stale: age={heartbeat_age:.1f}s, limit={max_heartbeat_age:.1f}s",
        )
    chat_url = data.get("chat_url")
    if not isinstance(chat_url, str) or not CHAT_URL_RE.match(chat_url):
        raise M2AcceptanceError("browser", f"invalid ChatGPT URL: {chat_url!r}")
    if expected_chat_url is not None and chat_url != expected_chat_url:
        raise M2AcceptanceError(
            "browser",
            f"ChatGPT conversation URL changed: expected {expected_chat_url!r}, observed {chat_url!r}",
        )
    if data.get("auth_required") is True:
        raise M2AcceptanceError("browser", "ChatGPT authentication/security verification is required")
    if data.get("provider_usage_limited") is True:
        raise M2AcceptanceError("browser", "provider usage is limited")
    if data.get("conversation_context_exhausted") is True:
        raise M2AcceptanceError("browser", "current conversation is context-exhausted")
    if data.get("composer_present") is not True:
        raise M2AcceptanceError("browser", "ChatGPT composer is not present")
    if parse_signature(data.get("conversation_signature")) is None:
        raise M2AcceptanceError("browser", "browser health does not provide a usable conversation signature")
    return heartbeat_age


def bridge_is_healthy() -> bool:
    request = urllib.request.Request(BRIDGE_URL + "/health", method="GET")
    try:
        with urllib.request.urlopen(request, timeout=3):
            return True
    except (OSError, urllib.error.URLError):
        return False


def start_managed_run(runtime_dir: Path, branch: str, task: str) -> tuple[str, str, str, float]:
    env = os.environ.copy()
    env.update(
        {
            "PASI_RUNTIME_DIR": str(runtime_dir),
            "PASI_OVERNIGHT_BRANCH": branch,
            "PASI_SUPERVISOR_MAX_RESTARTS": "0",
            "PASI_LOCAL_GATE_MODE": "fast",
            "PASI_M2_MANUAL_RELOAD_GATE": "1",
            "PASI_M2_FAST_START": "1",
        }
    )
    started_at = time.monotonic()
    result = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "start_pasi_168h.sh"), "--task", task, "--no-push"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    elapsed_seconds = time.monotonic() - started_at
    if result.returncode != 0:
        raise M2AcceptanceError("start", f"start_pasi_168h.sh failed (runtime_dir={runtime_dir}, elapsed={elapsed_seconds:.3f}s):\nSTDOUT:\n{result.stdout[-6000:]}\nSTDERR:\n{result.stderr[-6000:]}")
    worktree = re.search(r"^Worktree:\s*(.+)$", result.stdout, re.MULTILINE)
    branch_match = re.search(r"^Branch:\s*(.+)$", result.stdout, re.MULTILINE)
    if not worktree or not branch_match:
        raise M2AcceptanceError("start", "start_pasi_168h.sh did not report its worktree and branch")
    return worktree.group(1).strip(), branch_match.group(1).strip(), result.stdout[-8000:], elapsed_seconds


def start_bridge(runtime_dir: Path) -> dict[str, Any]:
    python = REPO_ROOT / ".venv" / "bin" / "python"
    log_path = runtime_dir / "bridge.log"
    pid_path = runtime_dir / "bridge.pid"
    env = os.environ.copy()
    env.update({"PASI_RUNTIME_DIR": str(runtime_dir), "PASI_BRIDGE_TOKEN": token()})
    command = [
        "bash", "-c", 'exec 9>&-; exec "$@"', "_", "env",
        f"PYTHONPATH={REPO_ROOT}:{env.get('PYTHONPATH', '')}",
        str(python), str(REPO_ROOT / "scripts" / "pasi_log_router.py"),
        "--log", str(log_path), "--max-bytes", "1048576", "--backups", "2", "--",
        str(python), "-m", "automation.orchestrator.bridge",
    ]
    process = subprocess.Popen(
        command,
        cwd=REPO_ROOT,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    pid_path.write_text(f"{process.pid}\n", encoding="utf-8")
    wait_for(bridge_is_healthy, 20, "bridge restart")
    return {"pid": process.pid, "started_at": utc_now(), "pid_file": str(pid_path)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the M2 kill/restart live recovery acceptance gate.")
    parser.add_argument("--runtime-dir", default=None)
    parser.add_argument("--timeout", type=float, default=900.0)
    args = parser.parse_args()

    explicit_runtime_dir = args.runtime_dir or os.environ.get("PASI_RUNTIME_DIR")
    if explicit_runtime_dir:
        runtime_dir = Path(explicit_runtime_dir).expanduser().resolve()
        runtime_dir_source = "explicit"
    else:
        run_stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        runtime_dir = (
            DEFAULT_RUNTIME_BASE_DIR
            / f"{run_stamp}-{uuid.uuid4().hex[:8]}"
        ).resolve()
        runtime_dir_source = "isolated"
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    artifact_path = ARTIFACT_DIR / f"m2-live-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}.json"
    evidence: dict[str, Any] = {
        "gate": "M2", "status": "FAIL", "started_at": utc_now(),
        "runtime_dir": str(runtime_dir), "runtime_dir_source": runtime_dir_source, "artifact": str(artifact_path), "stages": {},
    }
    stage = "preflight"

    def save() -> None:
        evidence["finished_at"] = utc_now()
        artifact_path.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    runner_started = False
    bridge_was_stopped = False
    bridge_restart_succeeded = False
    try:
        runner_pid = read_pid(runtime_dir, "runner.pid")
        supervisor_pid = read_pid(runtime_dir, "supervisor.pid")
        if process_exists(runner_pid) or process_exists(supervisor_pid):
            raise M2AcceptanceError("preflight", f"M2 requires an idle managed runtime; runner={runner_pid}, supervisor={supervisor_pid}")

        bridge_preflight: dict[str, Any] = {"healthy_before_start": bridge_is_healthy()}
        if bridge_preflight["healthy_before_start"]:
            managed_bridge_pid = read_pid(runtime_dir, "bridge.pid")
            if managed_bridge_pid is not None:
                command_line = process_command(managed_bridge_pid)
                if (
                    process_exists(managed_bridge_pid)
                    and is_managed_bridge_process(command_line, process_cwd(managed_bridge_pid))
                ):
                    bridge_preflight["bridge_pid"] = managed_bridge_pid
                    bridge_preflight["adopted_existing_bridge"] = False
                else:
                    managed_bridge_pid = None
            if managed_bridge_pid is None:
                discovered = discover_managed_bridge_pid()
                if discovered is None:
                    raise M2AcceptanceError(
                        "preflight",
                        "port 8765 is occupied by an unmanaged bridge; refusing to kill an unknown process",
                    )
                managed_bridge_pid, discovery = discovered
                runtime_dir.mkdir(parents=True, exist_ok=True)
                (runtime_dir / "bridge.pid").write_text(f"{managed_bridge_pid}\n", encoding="utf-8")
                bridge_preflight.update(
                    {
                        "bridge_pid": managed_bridge_pid,
                        "adopted_existing_bridge": True,
                        "discovery": discovery,
                    }
                )
        else:
            bridge_preflight["bridge_pid"] = None
            bridge_preflight["adopted_existing_bridge"] = False
        evidence["stages"]["preflight"] = bridge_preflight

        health = browser_health()
        chat_url = str(health.get("chat_url") or "")
        baseline_signature = health.get("conversation_signature")
        controller_expected = expected_controller_version(REPO_ROOT)
        extension_expected = expected_extension_manifest_version(REPO_ROOT)
        heartbeat_age = validate_browser_health(
            health,
            controller_expected,
            extension_expected,
            BROWSER_MAX_HEARTBEAT_AGE_SECONDS,
            require_manual_reload_gate_capability=True,
        )
        evidence["stages"]["browser_preflight"] = {
            "captured_at": health.get("captured_at"),
            "heartbeat_age_seconds": round(heartbeat_age, 3),
            "controller_version_expected": controller_expected,
            "controller_version_actual": health.get("controller_version"),
            "extension_manifest_version_expected": extension_expected,
            "extension_manifest_version_actual": health.get("extension_manifest_version"),
            "manual_reload_gate_supported": health.get("manual_reload_gate_supported"),
            "native_controller": health.get("native_controller"),
            "composer_present": health.get("composer_present"),
            "conversation_signature": baseline_signature,
            "chat_url": chat_url,
        }

        marker = f"M2_ACCEPTANCE_{uuid.uuid4().hex[:10]}"
        task = (
            "Complete this isolated live M2 recovery acceptance fixture. Verify the requested operation identity and "
            "return the required result contract with concise, task-relevant evidence. This is an acceptance fixture, "
            "not a roadmap task; it does not require repository implementation changes. Keep internal controller, "
            "planner, capability-gateway, and orchestration details out of the response. Do not treat the task as "
            "terminal until this same operation is explicitly released after the manual tab reload and process recovery. "
            f"Include the exact token {marker} on its own line near the end of the final response. "
            "PASI_M2_MANUAL_RELOAD_GATE: true. "
            "Run relevant verification checks before reporting completion and repair any failure you can reproduce."
        )
        branch = f"pasi/m2-live-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
        worktree, actual_branch, start_output, launcher_start_seconds = start_managed_run(runtime_dir, branch, task)
        runner_started = True
        queue_wait_started = time.monotonic()

        try:
            operation_id = wait_for(
                lambda: next(
                    (
                        item.get("operation_id")
                        for item in queue_items()
                        if marker in str(item.get("prompt") or "") and isinstance(item.get("operation_id"), str)
                    ),
                    None,
                ),
                OPERATION_QUEUE_TIMEOUT_SECONDS,
                f"M2 operation {marker} to be queued",
                poll_seconds=OPERATION_POLL_SECONDS,
            )
        except M2AcceptanceError as exc:
            queue_wait_seconds = time.monotonic() - queue_wait_started
            diagnostics = runtime_startup_diagnostics(runtime_dir)
            evidence["stages"]["operation_start_timeout"] = diagnostics
            raise M2AcceptanceError(
                "operation_start",
                f"{exc}; runtime startup diagnostics: {json.dumps(diagnostics, ensure_ascii=False)[:16000]}",
            ) from exc
        queue_wait_seconds = time.monotonic() - queue_wait_started
        active_wait_started = time.monotonic()
        wait_for(
            lambda: operation(operation_id) if operation(operation_id).get("status") in {"claimed", "generating"} else None,
            120,
            f"operation {operation_id} to become active",
            poll_seconds=OPERATION_POLL_SECONDS,
        )
        active_wait_seconds = time.monotonic() - active_wait_started
        gate_wait_started = time.monotonic()
        manual_gate_operation = wait_for(
            lambda: (
                operation(operation_id)
                if operation(operation_id).get("manual_reload_gate") is True
                and operation(operation_id).get("manual_reload_gate_armed") is True
                and operation(operation_id).get("manual_reload_gate_released") is not True
                else None
            ),
            180,
            f"manual reload gate for operation {operation_id} to be armed",
            poll_seconds=OPERATION_POLL_SECONDS,
        )
        gate_wait_seconds = time.monotonic() - gate_wait_started
        marker_operation_ids = queue_operation_ids(marker)
        if marker_operation_ids != [operation_id]:
            raise M2AcceptanceError(
                "operation_start",
                f"M2 marker is not uniquely bound to the original operation: {marker_operation_ids!r}",
            )
        evidence["stages"]["operation_start"] = {
            "completed_at": utc_now(),
            "operation_id": operation_id,
            "marker": marker,
            "baseline_signature": baseline_signature,
            "chat_url": chat_url,
            "operation": manual_gate_operation,
            "manual_reload_gate_armed": True,
            "start_output": start_output,
            "launcher_start_seconds": round(launcher_start_seconds, 3),
            "queue_wait_seconds": round(queue_wait_seconds, 3),
            "active_wait_seconds": round(active_wait_seconds, 3),
            "manual_gate_wait_seconds": round(gate_wait_seconds, 3),
            "worktree": worktree,
            "branch": actual_branch,
            "marker_operation_ids": marker_operation_ids,
        }

        print("\n=== M2 MANUAL CHECKPOINT ===")
        print(f"Operation ID: {operation_id}")
        print(f"Chat URL:     {chat_url}")
        print(f"Marker:       {marker}")
        print("Close or reload the EXACT ChatGPT conversation tab carrying this operation.")
        print("PASI will attempt to reopen the same conversation automatically when the tab is absent.")
        print("Do not open a replacement conversation and do not send another message.")
        print("Fallback WSL reopen command:")
        print(f'  powershell.exe -NoProfile -Command "Start-Process \'{chat_url}\'"')
        print("Fallback Windows command:")
        print(f'  cmd.exe /c start "" "{chat_url}"')
        print("Use the fallback only if PASI has not reopened the exact URL; then press Enter.")
        input("Press Enter after that exact tab is closed/reloaded: ")
        reload_confirmed_at = utc_now()

        def fresh_reload_health() -> dict[str, Any] | None:
            candidate = browser_health()
            try:
                validate_browser_health(
                    candidate,
                    controller_expected,
                    extension_expected,
                    BROWSER_MAX_HEARTBEAT_AGE_SECONDS,
                    expected_chat_url=chat_url,
                    require_manual_reload_gate_capability=True,
                )
            except M2AcceptanceError:
                return None
            return candidate

        after_reload_health = wait_for(
            fresh_reload_health,
            30,
            "fresh native browser health after the manual exact-tab reload",
        )
        after_reload = operation(operation_id)
        if after_reload.get("status") in {"completed", "failed", "cancelled"}:
            raise M2AcceptanceError("manual_reload", f"operation became terminal before process recovery: {after_reload.get('status')!r}")
        if after_reload.get("manual_reload_gate") is not True or after_reload.get("manual_reload_gate_armed") is not True:
            raise M2AcceptanceError("manual_reload", "manual reload gate state was not preserved for the same operation")
        if after_reload.get("manual_reload_gate_released") is True:
            raise M2AcceptanceError("manual_reload", "manual reload gate was released before runner recovery")
        evidence["stages"]["manual_reload"] = {
            "confirmed_at": reload_confirmed_at,
            "health": after_reload_health,
            "operation": after_reload,
        }

        bridge_stop = kill_managed_tree(
            runtime_dir,
            "bridge.pid",
            ("pasi_log_router.py", "automation.orchestrator.bridge"),
        )
        bridge_was_stopped = True
        wait_for(lambda: not bridge_is_healthy(), 10, "bridge outage")
        bridge_down_at = utc_now()
        bridge_start = start_bridge(runtime_dir)
        bridge_restart_succeeded = True
        after_bridge = operation(operation_id)
        if after_bridge.get("status") in {"completed", "failed", "cancelled"}:
            raise M2AcceptanceError("bridge_restart", "operation became terminal during bridge restart")
        evidence["stages"]["bridge_restart"] = {
            "stopped": bridge_stop,
            "down_at": bridge_down_at,
            "restarted": bridge_start,
            "operation": after_bridge,
        }

        runner_pid_before = read_pid(runtime_dir, "runner.pid")
        supervisor_pid_before = read_pid(runtime_dir, "supervisor.pid")
        runner_log = runner_log_path(runtime_dir)
        runner_kill_log_offset = runner_log.stat().st_size if runner_log.exists() else 0
        current = operation(operation_id)
        if current.get("status") in {"completed", "failed", "cancelled"}:
            raise M2AcceptanceError("runner_kill", "operation became terminal before runner kill")
        runner_stop = kill_managed_tree(runtime_dir, "runner.pid", "pasi_extended_runtime_entrypoint.py")
        wait_for(lambda: not process_exists(runner_pid_before), 10, "runner shutdown")
        if supervisor_pid_before is not None:
            wait_for(lambda: not process_exists(supervisor_pid_before), 20, "zero-restart supervisor shutdown")
        restart_budget_log = wait_for(
            lambda: (
                read_log_since(runner_log, runner_kill_log_offset)
                if "restart budget exhausted after 0 rapid engine exits" in read_log_since(runner_log, runner_kill_log_offset)
                else None
            ),
            20,
            "zero-restart supervisor budget exhaustion evidence",
        )
        marker_ids_after_runner_kill = queue_operation_ids(marker)
        if marker_ids_after_runner_kill != [operation_id]:
            raise M2AcceptanceError(
                "runner_kill",
                f"M2 marker operation changed or duplicated while the runner was killed: {marker_ids_after_runner_kill!r}",
            )
        runner_started = False
        evidence["stages"]["runner_kill"] = {
            "runner_pid": runner_pid_before,
            "supervisor_pid": supervisor_pid_before,
            "operation_before_kill": current,
            "stopped": runner_stop,
            "killed_at": utc_now(),
            "restart_budget_evidence": restart_budget_log[-12000:],
            "marker_operation_ids": marker_ids_after_runner_kill,
        }

        resume_log = runner_log_path(runtime_dir)
        resume_log_offset = resume_log.stat().st_size if resume_log.exists() else 0
        env = os.environ.copy()
        env.update({
            "PASI_RUNTIME_DIR": str(runtime_dir),
            "PASI_OVERNIGHT_BRANCH": actual_branch,
            "PASI_OVERNIGHT_WORKTREE": worktree,
            "PASI_SUPERVISOR_MAX_RESTARTS": "0",
            "PASI_LOCAL_GATE_MODE": "fast",
            "PASI_M2_MANUAL_RELOAD_GATE_RELEASE": "1",
        })
        resumed = subprocess.run(
            ["bash", str(REPO_ROOT / "scripts" / "start_pasi_168h.sh"), "--resume", "--no-push"],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        resume_output = resumed.stdout[-12000:]
        if resumed.returncode != 0:
            raise M2AcceptanceError("resume", f"resume command failed: {resume_output}\n{resumed.stderr[-4000:]}")
        resume_log_delta = wait_for(
            lambda: (
                read_log_since(resume_log, resume_log_offset)
                if f"Resuming persisted ChatGPT operation: {operation_id}" in read_log_since(resume_log, resume_log_offset)
                else None
            ),
            120,
            f"persisted ChatGPT operation {operation_id} to be resumed in runner.log",
        )
        resume_ids = RESUME_OP_RE.findall(resume_log_delta)
        prompt_ids = PROMPT_OP_RE.findall(resume_log_delta)
        retry_ids = RETRY_OP_RE.findall(resume_log_delta)
        if operation_id not in resume_ids:
            raise M2AcceptanceError("resume", f"original operation {operation_id} was not explicitly resumed in runner.log: {resume_ids!r}")
        if retry_ids:
            raise M2AcceptanceError("resume", f"resume created an unexpected retry operation: {retry_ids!r}")
        release_response = request_json(
            "/chat/manual-reload-gate/release",
            method="POST",
            payload={"operation_id": operation_id},
        )
        if release_response.get("operation", {}).get("manual_reload_gate_released") is not True:
            raise M2AcceptanceError("resume", "manual reload gate release was not durably acknowledged for the original operation")
        marker_ids_after_resume = queue_operation_ids(marker)
        if marker_ids_after_resume != [operation_id]:
            raise M2AcceptanceError(
                "resume",
                f"M2 marker produced duplicate or changed operations after resume: {marker_ids_after_resume!r}",
            )
        evidence["stages"]["resume"] = {
            "completed_at": utc_now(),
            "resume_stdout": resume_output,
            "runner_log_offset": resume_log_offset,
            "runner_log_delta": resume_log_delta[-12000:],
            "resumed_operation_ids": resume_ids,
            "prompt_operation_ids": prompt_ids,
            "retry_operation_ids": retry_ids,
            "manual_reload_gate_release": release_response.get("operation"),
            "marker_operation_ids": marker_ids_after_resume,
        }

        runner_started = True
        final_operation = wait_for(
            lambda: operation(operation_id) if operation(operation_id).get("status") in {"completed", "failed", "cancelled"} else None,
            args.timeout,
            f"operation {operation_id} to complete",
        )
        final_response = browser_response()
        if final_operation.get("status") != "completed":
            raise M2AcceptanceError("final_verification", f"operation ended as {final_operation.get('status')!r}")
        if str(final_response.get("active_operation_id") or final_response.get("operation_id") or "") != operation_id:
            raise M2AcceptanceError("final_verification", "final browser response belongs to another operation")
        response_text = str(final_operation.get("response_text") or final_response.get("response_text") or "")
        if marker not in response_text:
            raise M2AcceptanceError("final_verification", f"final response missing marker {marker!r}")
        final_chat_url = str(final_operation.get("chat_url") or final_response.get("chat_url") or "")
        if final_chat_url != chat_url:
            raise M2AcceptanceError("final_verification", "final response changed conversation URL")
        timing = final_operation.get("timing")
        if not isinstance(timing, dict) or timing.get("user_messages_added") != 1 or timing.get("ack_verified") is not True:
            raise M2AcceptanceError("final_verification", f"durable submission timing is not exact-once: {timing!r}")
        if not isinstance(timing.get("submission_via"), str) or not timing["submission_via"].strip():
            raise M2AcceptanceError("final_verification", "submission mechanism is missing from timing evidence")
        final_signature = final_response.get("conversation_signature")
        validate_signature_progression(baseline_signature, final_signature)
        marker_operation_ids_final = queue_operation_ids(marker)
        if marker_operation_ids_final != [operation_id]:
            raise M2AcceptanceError(
                "final_verification",
                f"M2 marker is bound to unexpected operation IDs at completion: {marker_operation_ids_final!r}",
            )
        evidence["final"] = {
            "operation_id": operation_id,
            "marker": marker,
            "operation": final_operation,
            "browser_response": final_response,
            "baseline_signature": baseline_signature,
            "final_signature": final_signature,
            "chat_url": chat_url,
            "reload_confirmed_at": reload_confirmed_at,
            "marker_operation_ids": marker_operation_ids_final,
        }
        evidence["status"] = "PASS"
        save()
        print(f"M2 PASS: original operation {operation_id} resumed exactly once and completed in the same conversation")
        print(f"Evidence: {artifact_path}")
        return 0
    except M2AcceptanceError as exc:
        cleanup: dict[str, Any] = {}
        if runner_started:
            supervisor_cleanup = try_kill_managed_tree(
                runtime_dir,
                "supervisor.pid",
                ("pasi_168h_supervisor.sh",),
            )
            runner_cleanup = try_kill_managed_tree(
                runtime_dir,
                "runner.pid",
                ("pasi_extended_runtime_entrypoint.py",),
            )
            cleanup["supervisor"] = supervisor_cleanup
            cleanup["runner"] = runner_cleanup
        if bridge_was_stopped and not bridge_restart_succeeded and not bridge_is_healthy():
            try:
                cleanup["bridge_restore"] = start_bridge(runtime_dir)
            except Exception as restore_exc:
                cleanup["bridge_restore_error"] = str(restore_exc)
        evidence["cleanup"] = cleanup
        evidence["failure"] = {"stage": exc.stage, "message": str(exc)}
        save()
        print(f"M2 FAIL ({exc.stage}): {exc}", file=sys.stderr)
        print(f"Evidence: {artifact_path}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
