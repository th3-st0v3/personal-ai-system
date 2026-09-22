#!/usr/bin/env python3
"""Run PASI's complete Python test suite under branch coverage."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from scripts.run_free_acceptance import test_environment

ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str], env: dict[str, str]) -> None:
    completed = subprocess.run(command, cwd=ROOT, env=env, check=False)
    if completed.returncode:
        rendered = " ".join(command)
        raise SystemExit(f"coverage command failed with exit code {completed.returncode}: {rendered}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / ".runtime" / "coverage",
    )
    args = parser.parse_args()

    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    env = test_environment()
    data_file = output_dir / "coverage"

    run(
        [
            sys.executable,
            "-m",
            "coverage",
            "run",
            "--branch",
            f"--data-file={data_file}",
            "-m",
            "pytest",
            "-q",
        ],
        env,
    )
    run(
        [sys.executable, "-m", "coverage", "report", f"--data-file={data_file}"],
        env,
    )
    run(
        [
            sys.executable,
            "-m",
            "coverage",
            "xml",
            f"--data-file={data_file}",
            "-o",
            str(output_dir / "coverage.xml"),
        ],
        env,
    )
    run(
        [
            sys.executable,
            "-m",
            "coverage",
            "html",
            f"--data-file={data_file}",
            "-d",
            str(output_dir / "html"),
        ],
        env,
    )
    print(f"Python coverage evidence written to {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
