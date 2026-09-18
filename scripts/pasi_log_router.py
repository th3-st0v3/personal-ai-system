#!/usr/bin/env python3
"""Run a long-lived command with bounded stdout/stderr logs.

The child process remains the real service process from the service's
perspective; this wrapper only owns the log file and forwards the child's
exit status. Logs rotate before they can grow without bound.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


DEFAULT_MAX_BYTES = 2 * 1024 * 1024
DEFAULT_BACKUPS = 4


def rotate_log(path: Path, backups: int) -> None:
    if backups <= 0:
        path.unlink(missing_ok=True)
        return

    oldest = path.with_name(f"{path.name}.{backups}")
    oldest.unlink(missing_ok=True)

    for index in range(backups - 1, 0, -1):
        source = path.with_name(f"{path.name}.{index}")
        destination = path.with_name(f"{path.name}.{index + 1}")
        if source.exists():
            source.replace(destination)

    if path.exists():
        path.replace(path.with_name(f"{path.name}.1"))


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
        text=True,
        bufsize=1,
    )

    assert process.stdout is not None
    with log_path.open("a", encoding="utf-8", buffering=1) as log:
        for line in process.stdout:
            encoded_size = len(line.encode("utf-8"))
            if current_size and current_size + encoded_size > max_bytes:
                log.flush()
                os.fsync(log.fileno())
                log.close()
                rotate_log(log_path, backups)
                log = log_path.open("a", encoding="utf-8", buffering=1)
                current_size = 0

            log.write(line)
            log.flush()
            current_size += encoded_size

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
