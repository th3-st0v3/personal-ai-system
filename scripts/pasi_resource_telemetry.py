#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STOP = False
MAX_SAMPLE_FILE_BYTES = 16 * 1024 * 1024
MAX_RETAINED_SAMPLES = 25_000


def on_signal(_signum: int, _frame: object) -> None:
    global STOP
    STOP = True


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def pid_from_file(path: Path) -> int | None:
    try:
        raw = path.read_text(encoding="utf-8").strip()
        pid = int(raw)
    except (OSError, ValueError):
        return None
    return pid if pid > 0 else None


def process_sample(pid: int | None) -> dict[str, Any]:
    if pid is None:
        return {"status": "not_managed"}
    proc = Path("/proc") / str(pid)
    if not proc.exists():
        return {"pid": pid, "status": "not_running"}

    result: dict[str, Any] = {"pid": pid, "status": "running"}
    try:
        for line in (proc / "status").read_text(encoding="utf-8", errors="replace").splitlines():
            key, _, raw = line.partition(":")
            if key == "VmRSS":
                result["rss_kib"] = int(raw.strip().split()[0])
            elif key == "VmSize":
                result["virtual_memory_kib"] = int(raw.strip().split()[0])
            elif key == "Threads":
                result["threads"] = int(raw.strip())
    except (OSError, ValueError):
        result["status"] = "unreadable"

    try:
        result["cpu_percent"] = float(
            subprocess.run(
                ["ps", "-p", str(pid), "-o", "%cpu="],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            ).stdout.strip()
        )
    except (OSError, ValueError, subprocess.TimeoutExpired):
        result["cpu_percent"] = None

    try:
        result["command"] = (
            subprocess.run(
                ["ps", "-p", str(pid), "-o", "args="],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            ).stdout.strip()
        )
    except (OSError, subprocess.TimeoutExpired):
        result["command"] = ""
    return result


def append_record(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False) + "\n"
    if path.exists():
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        if size + len(line.encode("utf-8")) > MAX_SAMPLE_FILE_BYTES:
            try:
                lines = path.read_text(encoding="utf-8").splitlines()[-(MAX_RETAINED_SAMPLES - 1):]
                temporary = path.with_suffix(path.suffix + ".tmp")
                temporary.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
                temporary.replace(path)
            except OSError:
                return
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())


def main() -> int:
    parser = argparse.ArgumentParser(description="Persist bounded PASI runtime resource samples.")
    parser.add_argument("--runtime-dir", type=Path, required=True)
    parser.add_argument("--interval", type=float, default=30.0)
    args = parser.parse_args()
    if args.interval <= 0:
        parser.error("--interval must be positive")

    runtime_dir = args.runtime_dir.expanduser().resolve()
    runtime_dir.mkdir(parents=True, exist_ok=True)
    pid_files = {
        "runner": runtime_dir / "runner.pid",
        "supervisor": runtime_dir / "supervisor.pid",
        "bridge": runtime_dir / "bridge.pid",
    }
    output = runtime_dir / "resource-samples.jsonl"
    own_pid_file = runtime_dir / "resource-telemetry.pid"

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)
    own_pid_file.write_text(f"{os.getpid()}\n", encoding="utf-8")

    try:
        while not STOP:
            state = load_json(runtime_dir / "state.json")
            run_id = str(state.get("run_id") or "")
            record = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "run_id": run_id,
                "processes": {
                    name: process_sample(pid_from_file(path))
                    for name, path in pid_files.items()
                },
            }
            append_record(output, record)
            end = time.monotonic() + args.interval
            while not STOP and time.monotonic() < end:
                time.sleep(min(1.0, max(0.1, end - time.monotonic())))
    finally:
        try:
            if own_pid_file.read_text(encoding="utf-8").strip() == str(os.getpid()):
                own_pid_file.unlink()
        except (OSError, FileNotFoundError):
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
