#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any


DEFAULT_RUNNER_ROOT = Path.home() / ".pasi" / "actions-runner"


def _read_cmdline(pid: int) -> str:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return ""
    return raw.replace(b"\x00", b" ").decode("utf-8", "replace").strip()


def _read_cwd(pid: int) -> str:
    try:
        return str(Path(f"/proc/{pid}/cwd").resolve())
    except OSError:
        return ""


def listener_process_present(runner_root: Path) -> bool:
    root = str(runner_root.resolve())
    if os.name != "posix":
        return False
    try:
        pids = [int(entry) for entry in os.listdir("/proc") if entry.isdigit()]
    except OSError:
        return False
    for pid in pids:
        cmdline = _read_cmdline(pid)
        cwd = _read_cwd(pid)
        if (
            "Runner.Listener" in cmdline
            or "run-helper" in cmdline
        ) and (root in cmdline or cwd == root or cwd.startswith(root + os.sep)):
            return True
    return False


def inspect_runner(environ: dict[str, str] | None = None, runner_root: Path | None = None) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    root = (runner_root or Path(env.get("PASI_RUNNER_ROOT", DEFAULT_RUNNER_ROOT))).expanduser().resolve()

    runner_environment = env.get("RUNNER_ENVIRONMENT", "")
    checks = {
        "runner_environment": runner_environment or "unknown",
        "runner_name": env.get("RUNNER_NAME", ""),
        "runner_os": env.get("RUNNER_OS", ""),
        "runner_arch": env.get("RUNNER_ARCH", ""),
        "runner_config_present": (root / ".runner").is_file(),
        "runner_listener_process": listener_process_present(root),
    }

    problems: list[str] = []
    if runner_environment:
        if runner_environment != "self-hosted":
            problems.append(f"RUNNER_ENVIRONMENT={runner_environment!r}, expected 'self-hosted'")
        if env.get("RUNNER_OS") != "Linux":
            problems.append(f"RUNNER_OS={env.get('RUNNER_OS')!r}, expected 'Linux'")
        if env.get("RUNNER_ARCH") != "X64":
            problems.append(f"RUNNER_ARCH={env.get('RUNNER_ARCH')!r}, expected 'X64'")
        if not env.get("RUNNER_NAME"):
            problems.append("RUNNER_NAME is empty")
        if not checks["runner_config_present"]:
            problems.append(f"runner configuration missing: {root / '.runner'}")
    else:
        if not checks["runner_config_present"]:
            problems.append(f"runner configuration missing: {root / '.runner'}")
        if not checks["runner_listener_process"]:
            problems.append("no GitHub Actions runner listener process was found for the configured runner root")

    return {
        "ok": not problems,
        "runner_root": str(root),
        "checks": checks,
        "problems": problems,
        "fallback": (
            "The self-hosted runner is not ready. Keep CI on self-hosted to avoid metered usage, "
            "or manually dispatch the test workflow with runner_mode=github-hosted only after usage limits are reset."
        ) if problems else (
            "Self-hosted runner is ready. The test workflow remains self-hosted by default."
        ),
    }


def main() -> int:
    payload = inspect_runner()
    print(json.dumps(payload, indent=2, sort_keys=True))
    if payload["ok"]:
        print("SELF_HOSTED_RUNNER_PREFLIGHT: PASS")
        return 0
    for problem in payload["problems"]:
        print(f"SELF_HOSTED_RUNNER_PREFLIGHT: FAIL: {problem}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
