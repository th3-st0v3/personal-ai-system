#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.pasi_runtime_telemetry import analyze, load_events

EXPECTED_RUNTIME_SECONDS = 168 * 60 * 60
RUNTIME_TOLERANCE_SECONDS = 5.0


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return default


def command(command: list[str], cwd: Path | None = None) -> str:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def process_snapshot(pid_value: object) -> dict[str, Any]:
    if isinstance(pid_value, bool):
        return {"pid": pid_value, "status": "invalid"}
    try:
        pid = int(pid_value)
    except (TypeError, ValueError):
        return {"pid": pid_value, "status": "invalid"}
    if pid <= 0:
        return {"pid": pid, "status": "invalid"}

    proc = Path("/proc") / str(pid)
    status_file = proc / "status"
    if not proc.exists():
        return {"pid": pid, "status": "not_running"}

    status = load_proc_status(status_file)
    result = {
        "pid": pid,
        "status": "running",
        "rss_kib": status.get("VmRSS_kB"),
        "virtual_memory_kib": status.get("VmSize_kB"),
        "threads": status.get("Threads"),
        "command": command(["ps", "-p", str(pid), "-o", "args="]),
        "cpu_percent": command(["ps", "-p", str(pid), "-o", "%cpu="]),
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }
    return result


def load_proc_status(path: Path) -> dict[str, Any]:
    values: dict[str, Any] = {}
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return values
    for line in lines:
        if ":\t" not in line:
            continue
        key, raw = line.split(":\t", 1)
        value = raw.strip()
        if key in {"VmRSS", "VmSize"} and value.endswith(" kB"):
            try:
                values[f"{key}_kB"] = int(value[:-3].strip())
            except ValueError:
                pass
        elif key == "Threads":
            try:
                values[key] = int(value)
            except ValueError:
                pass
    return values


def load_resource_samples(path: Path, run_id: str) -> tuple[list[dict[str, Any]], int]:
    samples: list[dict[str, Any]] = []
    malformed = 0
    if not path.is_file():
        return samples, 0
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return samples, 0
    for line in lines:
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            malformed += 1
            continue
        if not isinstance(value, dict):
            malformed += 1
            continue
        observed_run_id = str(value.get("run_id") or "")
        if run_id and observed_run_id != run_id:
            continue
        samples.append(value)
    return samples, malformed


def resource_peak_summary(samples: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {"samples": len(samples), "processes": {}}
    for process_name in ("runner", "supervisor", "bridge"):
        rss_values: list[int] = []
        cpu_values: list[float] = []
        for sample in samples:
            processes = sample.get("processes")
            process = processes.get(process_name) if isinstance(processes, dict) else None
            if not isinstance(process, dict):
                continue
            rss = process.get("rss_kib")
            cpu = process.get("cpu_percent")
            if isinstance(rss, int) and rss >= 0:
                rss_values.append(rss)
            if isinstance(cpu, (int, float)) and not isinstance(cpu, bool) and cpu >= 0:
                cpu_values.append(float(cpu))
        summary["processes"][process_name] = {
            "sample_count_with_process": max(len(rss_values), len(cpu_values)),
            "peak_rss_kib": max(rss_values) if rss_values else None,
            "peak_cpu_percent": max(cpu_values) if cpu_values else None,
        }
    return summary


def configured_resource_limits(root: Path) -> dict[str, Any]:
    path = root / "config" / "runner" / "capabilities.json"
    payload = load_json(path, {})
    if not isinstance(payload, dict):
        return {"source": str(path), "status": "unavailable"}
    resource = payload.get("resource_boundary")
    return {
        "source": str(path),
        "status": "configured" if isinstance(resource, dict) else "unavailable",
        "resource_boundary": resource if isinstance(resource, dict) else {},
    }


def parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def git_identity(worktree: Path) -> dict[str, Any]:
    return {
        "worktree": str(worktree),
        "branch": command(["git", "branch", "--show-current"], worktree),
        "head_sha": command(["git", "rev-parse", "HEAD"], worktree),
        "status_porcelain": command(["git", "status", "--porcelain", "--untracked-files=all"], worktree),
        "remote": command(["git", "remote", "get-url", "origin"], worktree),
    }


def pr_provenance(branch: str, number: int | None, url: str) -> dict[str, Any]:
    if number is not None:
        output = command(["gh", "pr", "view", str(number), "--json", "number,url,state,headRefName,headRefOid"])
        if output:
            try:
                payload = json.loads(output)
            except json.JSONDecodeError:
                return {"status": "provided_unverified", "number": number, "url": url, "reason": "gh returned non-JSON PR metadata"}
            if int(payload.get("number", 0) or 0) == number:
                return {
                    "status": "observed",
                    "number": number,
                    "url": payload.get("url") or url,
                    "state": payload.get("state"),
                    "head_ref": payload.get("headRefName"),
                    "head_sha": payload.get("headRefOid"),
                }
        return {
            "status": "provided_unverified",
            "number": number,
            "url": url,
            "reason": "gh could not verify the supplied PR identity",
        }
    if not branch:
        return {"status": "unavailable", "reason": "branch identity missing"}

    output = command(["gh", "pr", "view", branch, "--json", "number,url,state,headRefName,headRefOid"])
    if not output:
        return {
            "status": "unavailable",
            "reason": "gh CLI unavailable, unauthenticated, or no PR was found",
        }
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        return {"status": "unavailable", "reason": "gh returned non-JSON PR metadata"}
    return {
        "status": "observed",
        "number": payload.get("number"),
        "url": payload.get("url"),
        "state": payload.get("state"),
        "head_ref": payload.get("headRefName"),
        "head_sha": payload.get("headRefOid"),
    }


def classify_p04_status(
    configured_seconds: float | None,
    deadline_reached: bool,
    stop_reason: str,
    resource_sample_count: int,
    branch_matches: bool,
    worktree_clean: bool,
    pr_verified: bool,
) -> tuple[str, list[str]]:
    failures: list[str] = []
    runtime_shape_ok = (
        configured_seconds is not None
        and abs(configured_seconds - EXPECTED_RUNTIME_SECONDS) <= RUNTIME_TOLERANCE_SECONDS
    )
    if not deadline_reached:
        return "INCOMPLETE", ["168-hour deadline has not been reached"]
    if not runtime_shape_ok:
        failures.append("configured runtime window is not exactly 168 hours")
    if stop_reason != "deadline_reached":
        failures.append(f"run did not terminate with deadline_reached (got {stop_reason or 'empty'})")
    if resource_sample_count <= 0:
        failures.append("no historical periodic resource samples were recorded")
    if not branch_matches:
        failures.append("runtime branch does not match the persisted run branch")
    if not worktree_clean:
        failures.append("acceptance worktree is not clean at close-out")
    if not pr_verified:
        failures.append("PR provenance was not machine-verified")
    return ("PASS" if not failures else "FAIL"), failures

def main() -> int:
    parser = argparse.ArgumentParser(description="Assemble reproducible evidence for a PASI 168-hour runtime.")
    parser.add_argument("--runtime-dir", type=Path, default=Path(os.environ.get("PASI_RUNTIME_DIR", str(Path.home() / ".pasi" / "overnight"))))
    parser.add_argument("--worktree", type=Path, default=None)
    parser.add_argument("--pr-number", type=int, default=None)
    parser.add_argument("--pr-url", default="")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    runtime_dir = args.runtime_dir.expanduser().resolve()
    state_path = runtime_dir / "state.json"
    event_path = runtime_dir / "events.jsonl"
    state = load_json(state_path, {})
    if not isinstance(state, dict) or not state:
        print(f"error: missing or invalid runtime state: {state_path}")
        return 2

    worktree_text = str(state.get("worktree") or "").strip()
    worktree = (args.worktree or Path(worktree_text or ".")).expanduser().resolve()
    events, malformed = load_events(event_path)
    report = analyze(events, malformed)
    run_id = str(state.get("run_id") or "")
    resource_samples, malformed_resource = load_resource_samples(runtime_dir / "resource-samples.jsonl", run_id)

    started_at = state.get("started_at")
    deadline_at = state.get("deadline_at")
    start_dt = parse_timestamp(started_at)
    deadline_dt = parse_timestamp(deadline_at)
    configured_seconds = (
        (deadline_dt - start_dt).total_seconds()
        if start_dt is not None and deadline_dt is not None
        else None
    )
    now = datetime.now(timezone.utc)
    deadline_reached = deadline_dt is not None and now >= deadline_dt
    git = git_identity(worktree)
    expected_branch = str(state.get("branch") or "").strip()
    branch_matches = bool(expected_branch and git.get("branch") == expected_branch)
    worktree_clean = not str(git.get("status_porcelain") or "").strip()

    pid_files = {
        "runner": runtime_dir / "runner.pid",
        "supervisor": runtime_dir / "supervisor.pid",
        "bridge": runtime_dir / "bridge.pid",
    }
    pids = {}
    for name, path in pid_files.items():
        pids[name] = process_snapshot(read_text(path))

    pr = pr_provenance(
        git.get("branch") or str(state.get("branch") or ""),
        args.pr_number,
        args.pr_url.strip(),
    )
    stop_reason = str(state.get("stop_reason") or "").strip()
    result_status, gate_failures = classify_p04_status(
        configured_seconds,
        deadline_reached,
        stop_reason,
        len(resource_samples),
        branch_matches,
        worktree_clean,
        pr.get("status") == "observed",
    )

    limitations: list[str] = []
    if malformed:
        limitations.append(f"{malformed} malformed event-log lines were ignored")
    if malformed_resource:
        limitations.append(f"{malformed_resource} malformed resource-sample lines were ignored")
    if not resource_samples:
        limitations.append("No historical periodic resource samples were available for this run.")
    if pr.get("status") != "observed":
        limitations.append("PR provenance is not machine-verified; rerun with a reachable GitHub CLI and the accepted PR number.")

    payload = {
        "gate": "P0.4",
        "status": result_status,
        "generated_at": now.isoformat(),
        "run": {
            "run_id": state.get("run_id"),
            "started_at": started_at,
            "deadline_at": deadline_at,
            "configured_runtime_seconds": configured_seconds,
            "deadline_reached": deadline_reached,
            "stop_reason": stop_reason,
            "phase": state.get("phase"),
            "current_task": state.get("current_task"),
            "completed_tasks": state.get("completed_tasks"),
            "failed_tasks": state.get("failed_tasks"),
            "task_number": state.get("task_number"),
        },
        "runtime_telemetry": {
            "events": report.events,
            "malformed_lines": report.malformed_lines,
            "task_attempts": report.task_attempts,
            "completed_tasks": report.completed_tasks,
            "failed_tasks": report.failed_tasks,
            "completion_rate": report.completion_rate,
            "recovery_events": report.recovery_events,
            "retry_cycle_exhaustions": report.retry_cycle_exhaustions,
            "provider_limit_events": report.provider_limit_events,
            "auth_events": report.auth_events,
            "repeated_task_numbers": report.repeated_task_numbers,
            "p50_response_latency_ms": report.p50_response_latency_ms,
            "p50_browser_handoff_ms": report.p50_browser_handoff_ms,
            "p95_browser_handoff_ms": report.p95_browser_handoff_ms,
            "p99_browser_handoff_ms": report.p99_browser_handoff_ms,
        },
        "failure_provenance": {
            "last_failure_signature": state.get("last_failure_signature", ""),
            "same_failure_cycles": state.get("same_failure_cycles", 0),
            "last_result": str(state.get("last_result") or "")[-6000:],
        },
        "git": git,
        "pr": pr,
        "resources": {
            "configured": configured_resource_limits(Path(__file__).resolve().parents[1]),
            "historical_periodic_samples": resource_peak_summary(resource_samples),
            "process_snapshots": pids,
        },
        "acceptance_checks": {
            "failures": gate_failures,
            "branch_matches": branch_matches,
            "worktree_clean": worktree_clean,
            "resource_sample_count": len(resource_samples),
            "pr_verified": pr.get("status") == "observed",
        },
        "limitations": limitations,
    }

    output = args.output.expanduser().resolve() if args.output else runtime_dir / "p0.4-long-run-evidence.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(output)
    print(json.dumps({"gate": "P0.4", "status": result_status, "evidence": str(output)}, ensure_ascii=False))
    return 0 if result_status == "PASS" else 3


if __name__ == "__main__":
    raise SystemExit(main())
