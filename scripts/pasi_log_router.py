#!/usr/bin/env python3
"""Run a long-lived command with bounded stdout/stderr logs.

The child process remains the real service process from the service's
perspective; this wrapper owns the log file and forwards the child's exit
status. Logs rotate before they can grow without bound.

On POSIX, the wrapped command runs in its own process group. Termination
signals received by the router are forwarded to that group so a managed
service cannot outlive its log router and leave an orphaned descendant.
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
from pathlib import Path


DEFAULT_MAX_BYTES = 2 * 1024 * 1024
DEFAULT_BACKUPS = 4
SHUTDOWN_GRACE_SECONDS = 2.0


def rotate_log(path: Path, backups: int) -> None:
    if backups <= 0:
        path.unlink(missing_ok=True)
        return

    path.with_name(f"{path.name}.{backups}").unlink(missing_ok=True)
    for index in range(backups - 1, 0, -1):
        source = path.with_name(f"{path.name}.{index}")
        destination = path.with_name(f"{path.name}.{index + 1}")
        if source.exists():
            source.replace(destination)
    if path.exists():
        path.replace(path.with_name(f"{path.name}.1"))


def terminate_process_group(
    process: subprocess.Popen[bytes],
    signum: int,
    *,
    grace_seconds: float,
) -> None:
    if process.poll() is not None:
        return

    if os.name == "posix":
        try:
            os.killpg(process.pid, signum)
        except ProcessLookupError:
            return
    else:
        process.send_signal(signum)

    try:
        process.wait(timeout=grace_seconds)
        return
    except subprocess.TimeoutExpired:
        pass

    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
    else:
        process.kill()

    try:
        process.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        # The caller will still fail closed by exiting the router. There is no
        # safe reason to keep waiting forever on a managed-service shutdown.
        pass


def run(command: list[str], log_path: Path, max_bytes: int, backups: int) -> int:
    if not command:
        raise ValueError("a command is required")
    if max_bytes <= 0:
        raise ValueError("max-bytes must be positive")
    if backups < 0:
        raise ValueError("backups must be non-negative")

    log_path.parent.mkdir(parents=True, exist_ok=True)
    current_size = log_path.stat().st_size if log_path.exists() else 0

    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=False,
        bufsize=0,
        start_new_session=(os.name == "posix"),
    )

    def handle_signal(signum: int, _frame: object) -> None:
        # Forward termination to the entire wrapped process group. Raising
        # SystemExit immediately after bounded cleanup is intentional: stdout
        # reads can otherwise block forever on a child that ignores SIGTERM.
        terminate_process_group(
            process,
            signum,
            grace_seconds=SHUTDOWN_GRACE_SECONDS,
        )
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    assert process.stdout is not None
    stdout = process.stdout
    log = log_path.open("ab", buffering=0)
    try:
        for chunk in iter(lambda: stdout.readline(), b""):
            offset = 0
            while offset < len(chunk):
                if current_size >= max_bytes:
                    os.fsync(log.fileno())
                    log.close()
                    rotate_log(log_path, backups)
                    log = log_path.open("ab", buffering=0)
                    current_size = 0

                writable = min(max_bytes - current_size, len(chunk) - offset)
                log.write(chunk[offset : offset + writable])
                offset += writable
                current_size += writable

                if current_size >= max_bytes and offset < len(chunk):
                    os.fsync(log.fileno())
                    log.close()
                    rotate_log(log_path, backups)
                    log = log_path.open("ab", buffering=0)
                    current_size = 0
    finally:
        log.close()
        stdout.close()

    return process.wait()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", required=True, type=Path)
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    parser.add_argument("--backups", type=int, default=DEFAULT_BACKUPS)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    command = args.command
    if command[:1] == ["--"]:
        command = command[1:]
    try:
        return run(command, args.log, args.max_bytes, args.backups)
    except Exception as exc:
        print(f"pasi_log_router: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
