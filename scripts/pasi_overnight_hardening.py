from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
import sys
from pathlib import Path
from typing import Any

from automation.computer_use.obstacles import ObstacleLedger
from scripts import pasi_overnight_engine as engine
from scripts import pasi_overnight_engine_v2 as supervisor


_FORBIDDEN_PATH_PARTS = frozenset({".git", ".env", ".env.local", ".env.production"})
_FORBIDDEN_PATH_PATTERNS = (
    re.compile(r"(^|/)(id_rsa|id_ed25519|authorized_keys)$", re.IGNORECASE),
    re.compile(r"(^|/)(credentials|secrets?)(\.|/|$)", re.IGNORECASE),
)
_DIFF_PATH_RE = re.compile(r"^diff --git a/(.+) b/(.+)$", re.MULTILINE)
_DELETION_FILE_HEADER_RE = re.compile(r"^(?:deleted file mode \d+\n)?--- a/[^\n]+\n\+\+\+ /dev/null$", re.MULTILINE)
_AUTOMATION_CONTINUE_RE = re.compile(r"^PASI_AUTOMATION_CONTINUE:\s*true$", re.MULTILINE | re.IGNORECASE)
_BRIDGE_HEALTH_URL = "http://127.0.0.1:8765/health"
_STANDBY_SECONDS = 30.0


def validate_patch_paths(patch: str, allow_delete: bool) -> None:
    if len(patch.encode("utf-8")) > engine.MAX_PATCH_BYTES:
        raise ValueError("model patch exceeds configured size bound")
    if "new file mode 120000" in patch or "new file mode 160000" in patch:
        raise ValueError("symlink and submodule additions are not allowed in unattended patches")
    matches = _DIFF_PATH_RE.findall(patch)
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
            if any(part in _FORBIDDEN_PATH_PARTS for part in parts):
                raise ValueError(f"forbidden patch path: {path_value}")
            if any(pattern.search(normalized) for pattern in _FORBIDDEN_PATH_PATTERNS):
                raise ValueError(f"forbidden credential/secret path: {path_value}")
    is_deletion = bool(_DELETION_FILE_HEADER_RE.search(patch)) or bool(
        re.search(r"^--- [^\n]+\n\+\+\+ /dev/null$", patch, re.MULTILINE)
    )
    if is_deletion and not allow_delete:
        raise ValueError("file deletion requires PASI_RESULT_ALLOW_DELETE: true")


def _task_id(data: dict[str, Any]) -> str:
    value = data.get("task_number")
    return str(value) if value is not None else ""


def _record_event_obstacle(ledger: ObstacleLedger, kind: str, data: dict[str, Any]) -> None:
    mappings = {
        "verification_failed": (
            "verification_failed",
            "A proposed change failed deterministic verification.",
            "Review the recorded verification evidence; PASI will try a different task/approach rather than blocking the run.",
        ),
        "provider_pause": (
            "provider_pause",
            "A primary AI/provider route is temporarily unavailable or limited.",
            "Use the configured fallback provider or continue with an alternate engineering task; retry the primary route only when available.",
        ),
        "standby_auth_required": (
            "auth_challenge",
            "The ChatGPT/browser surface reported an interactive authentication or security challenge.",
            "Complete the interactive challenge when convenient; unattended PASI work continues through alternatives while it remains unresolved.",
        ),
        "run_failed": (
            "run_failure",
            "The unattended runner encountered a top-level failure.",
            "Inspect the recorded error and restart/resume the runner after the environment is repaired.",
        ),
    }
    selected = mappings.get(kind)
    if selected is None:
        return
    obstacle_kind, summary, next_action = selected
    details = {key: value for key, value in data.items() if key in {"error", "condition", "count", "phase", "task_number", "attempt"}}
    ledger.record(obstacle_kind, summary, next_action, task_id=_task_id(data), details=details)


def fallback_providers_available() -> list[str]:
    providers: list[str] = []
    if os.environ.get("OLLAMA_MODEL", "").strip() or os.environ.get("OLLAMA_BASE_URL", "").strip() or shutil.which("ollama"):
        providers.append("ollama")
    if shutil.which("opencode"):
        providers.append("opencode")
    if os.environ.get("OPENROUTER_API_KEY", "").strip():
        providers.append("openrouter")
    if os.environ.get("PERPLEXITY_API_KEY", "").strip():
        providers.append("perplexity")
    return providers


def nonblocking_ensure_services(*, ledger: ObstacleLedger) -> list[Any]:
    """Start local PASI helpers opportunistically without making them a startup gate."""
    children: list[Any] = []
    services = (
        (
            "bridge",
            supervisor.healthy(_BRIDGE_HEALTH_URL),
            [sys.executable, "-m", "automation.orchestrator.bridge"],
        ),
    )
    for service_name, already_healthy, command in services:
        if already_healthy:
            continue
        supervisor.log_event("service_start_nonblocking", service=service_name)
        try:
            children.append(subprocess.Popen(command, cwd=supervisor.REPO_ROOT))
        except OSError as exc:
            ledger.record(
                "service_unavailable",
                f"PASI local {service_name} service could not be started.",
                "Continue using fallback work; repair or restart the local service later and retry automatically on a future task.",
                status="waiting_external",
                details={"service": service_name, "error": str(exc)},
            )
    return children


def nonblocking_standby(state: Any, *, ledger: ObstacleLedger) -> bool:
    if supervisor.runtime_watchdog_is_live():
        return True

    providers = fallback_providers_available()
    if providers:
        ledger.record(
            "runtime_unavailable",
            "ChatGPT/browser heartbeat is unavailable or stale; a configured fallback provider is available.",
            "Proceed with the bounded fallback route; the next task will re-check the browser automatically.",
            details={
                "deadline_at": getattr(state, "deadline_at", ""),
                "fallback_providers": ",".join(providers),
            },
            status="pending",
        )
        supervisor.log_event(
            "standby_fallback_available",
            reason="browser heartbeat unavailable; continuing through configured fallback provider",
            providers=providers,
        )
        return True

    logged = False
    while not supervisor.STOP and supervisor.now_utc() < supervisor.datetime.fromisoformat(state.deadline_at):
        try:
            supervisor.ensure_services()
        except Exception as exc:
            supervisor.log_event("service_recovery_failed", error=str(exc)[-4_000:])

        if supervisor.runtime_watchdog_is_live():
            if logged:
                supervisor.log_event("standby_recovered")
            return True

        if not logged:
            ledger.record(
                "runtime_unavailable",
                "ChatGPT/browser heartbeat is unavailable or stale and no fallback provider is configured.",
                "Wait for the browser controller to recover instead of burning task attempts on repeated runtime failures.",
                details={"deadline_at": getattr(state, "deadline_at", "")},
                status="waiting_external",
            )
            supervisor.log_event(
                "standby_waiting_no_fallback",
                reason="browser heartbeat unavailable and no fallback provider is configured",
            )
            logged = True

        remaining = (
            supervisor.datetime.fromisoformat(state.deadline_at) - supervisor.now_utc()
        ).total_seconds()
        time.sleep(min(_STANDBY_SECONDS, max(1.0, remaining)))
    return False


def nonblocking_sleep(state: Any, seconds: float, *, ledger: ObstacleLedger) -> bool:
    if seconds > 0:
        ledger.record(
            "retry_backoff_deferred",
            f"A retry requested a {seconds:.0f}-second backoff.",
            "Backoff was converted to immediate continuation so the unattended scheduler can pursue alternative work.",
            details={"requested_seconds": seconds, "deadline_at": getattr(state, "deadline_at", "")},
            status="pending",
        )
    return not supervisor.STOP and supervisor.now_utc() < supervisor.datetime.fromisoformat(state.deadline_at)


def resilient_invoke_chat(task: str, state: Any, failure: str, *, ledger: ObstacleLedger) -> tuple[int, str]:
    prompt = supervisor.build_prompt(task, state, failure).replace(
        "- The repository is private; use the connected GitHub app when source/history context is required.",
        "- The repository is public; use public GitHub first. If public retrieval is unavailable, the ChatGPT launcher automatically falls back to the connected GitHub app in the same conversation.",
    )
    prompt += "\n\nAUTOMATION CONTINUATION: If this task's evidence/research reveals that another automation, computer-use, recovery, integration, or security capability is materially needed to satisfy the current objective, include exactly `PASI_AUTOMATION_CONTINUE: true` in your response. This tells PASI to keep improving automation instead of advancing to ordinary engineering work. Do not emit it merely for optional polish.\n"

    if not supervisor.runtime_watchdog_is_live():
        ledger.record(
            "browser_unavailable",
            "Primary ChatGPT browser runtime is not live.",
            "Attempt a configured provider fallback immediately and continue to the next task when no fallback is available.",
            task_id=str(getattr(state, "task_number", "")),
            status="waiting_external",
        )
        fallback = supervisor.command(
            [sys.executable, "scripts/pasi_provider_router.py", "--task", prompt, "--repo", str(state.worktree), "--timeout", "180"],
            Path(state.worktree),
            timeout=225.0,
        )
        if fallback[0] == 0 and fallback[1].strip():
            ledger.record(
                "browser_unavailable",
                "ChatGPT browser runtime was unavailable; fallback provider produced a response.",
                "Continue the task using the verified fallback response; return to ChatGPT when its heartbeat recovers.",
                task_id=str(getattr(state, "task_number", "")),
                status="pending",
                details={"fallback": "provider_router"},
            )
            return 0, fallback[1]
        return 92, fallback[1] or "CHAT_GUARD_TIMEOUT: browser runtime unavailable and no fallback provider succeeded"

    return supervisor.command(
        [sys.executable, "scripts/pasi_chat_guard.py", prompt, "--github", "auto", "--timeout", str(supervisor.TASK_TIMEOUT_SECONDS)],
        Path(state.worktree),
        timeout=supervisor.TASK_TIMEOUT_SECONDS + 45.0,
    )


def main() -> int:
    ledger = ObstacleLedger(supervisor.REPO_ROOT)
    original_validate = supervisor.validate_patch_paths
    original_watchdog = supervisor.runtime_watchdog_is_live
    original_sleep = supervisor.sleep_until_retry
    original_invoke = supervisor.invoke_chat
    original_log = supervisor.log_event
    original_gate = supervisor.automation_gate_is_satisfied
    original_parse = supervisor.parse_response
    original_services = supervisor.ensure_services
    automation_continue_requested = False

    def parse_response(response: str):
        nonlocal automation_continue_requested
        parsed = original_parse(response)
        if _AUTOMATION_CONTINUE_RE.search(response):
            automation_continue_requested = True
            status, summary, next_task, patch, allow_delete, values = parsed
            values = dict(values)
            values["automation_continue"] = "true"
            summary = (summary + " PASI_AUTOMATION_CONTINUE: true").strip()
            return status, summary, next_task, patch, allow_delete, values
        return parsed

    def log_event(kind: str, **data: Any) -> None:
        nonlocal automation_continue_requested
        original_log(kind, **data)
        _record_event_obstacle(ledger, kind, data)
        if kind == "task_failed":
            ledger.record(
                "task_failed",
                "A task exhausted its bounded retry budget.",
                "Continue with the next non-repeating task; use the recorded failure evidence to inform future recovery work.",
                task_id=_task_id(data),
                status="pending",
                details={"error": str(data.get("error", ""))[-3000:]},
            )

    def gate(evidence: dict[str, object]) -> bool:
        nonlocal automation_continue_requested
        if automation_continue_requested:
            automation_continue_requested = False
            return False
        return original_gate(evidence)

    supervisor.validate_patch_paths = validate_patch_paths
    supervisor.log_event = log_event
    supervisor.runtime_watchdog_is_live = original_watchdog
    supervisor.ensure_services = lambda: nonblocking_ensure_services(ledger=ledger)
    supervisor.standby_until_ready = lambda state: nonblocking_standby(state, ledger=ledger)
    supervisor.sleep_until_retry = lambda state, seconds: nonblocking_sleep(state, seconds, ledger=ledger)
    supervisor.invoke_chat = lambda task, state, failure: resilient_invoke_chat(task, state, failure, ledger=ledger)
    supervisor.automation_gate_is_satisfied = gate
    supervisor.parse_response = parse_response
    try:
        return supervisor.main()
    finally:
        supervisor.validate_patch_paths = original_validate
        supervisor.runtime_watchdog_is_live = original_watchdog
        supervisor.ensure_services = original_services
        supervisor.sleep_until_retry = original_sleep
        supervisor.invoke_chat = original_invoke
        supervisor.log_event = original_log
        supervisor.automation_gate_is_satisfied = original_gate
        supervisor.parse_response = original_parse
