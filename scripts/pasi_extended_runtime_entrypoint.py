from __future__ import annotations

import argparse
import math
import os
import sys
from pathlib import Path

from scripts import pasi_overnight_engine_v2 as supervisor

DEFAULT_TASK_FILE = Path.home() / ".pasi" / "current-project-task.md"
MAX_TASK_FILE_CHARS = 120_000
DEFAULT_ENGINEERING_TASK = """Advance the PASI Computer-Use Control Plane as a substantial engineering project. Inspect the existing architecture and runtime behavior, identify the highest-value missing end-to-end capability, implement it in the appropriate source modules, add or update deterministic tests, verify integration/runtime behavior, and iterate on failures. Do not stop at a read-only audit, documentation-only edit, cosmetic change, or trading-information task. Prefer work that reduces repeated human input and makes subsequent difficult engineering projects faster and more reliable. Preserve all authentication, authorization, path, network, approval, human-control, and verification boundaries."""
DIFFICULT_MODE_PREFIX = """DIFFICULT ENGINEERING PROJECT MODE:
Treat the assigned objective as implementation-heavy engineering work. Understand the relevant architecture before editing; implement a meaningful capability or defect fix; use deterministic verification; inspect integration behavior; and iterate when verification fails. Do not satisfy the objective solely with reading, explanation, documentation-only changes, or cosmetic edits unless documentation is explicitly the engineering objective. Never claim tests or evidence that were not actually produced. Preserve every existing PASI security, authorization, approval, human-control, and verification boundary.
"""


def validate_hours(hours: float) -> float:
    if not math.isfinite(hours) or hours < supervisor.MIN_HOURS:
        raise ValueError(f"--hours must be a finite value >= {supervisor.MIN_HOURS:g}")
    return hours


def load_task_file(path: Path) -> str:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise ValueError(f"PASI task file does not exist: {resolved}")
    text = resolved.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"PASI task file is empty: {resolved}")
    if len(text) > MAX_TASK_FILE_CHARS:
        raise ValueError(f"PASI task file exceeds {MAX_TASK_FILE_CHARS} characters: {resolved}")
    return text


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run PASI unattended for an extended duration with resilient response and recovery handling."
    )
    parser.add_argument("--hours", type=float, required=True)
    parser.add_argument("--task", default="")
    parser.add_argument("--task-file", type=Path, default=None)
    args, passthrough = parser.parse_known_args()
    hours = validate_hours(args.hours)

    configured_task_file = args.task_file
    if configured_task_file is None:
        environment_path = os.environ.get("PASI_TASK_FILE", "").strip()
        if environment_path:
            configured_task_file = Path(environment_path)
    if configured_task_file is None and DEFAULT_TASK_FILE.is_file():
        configured_task_file = DEFAULT_TASK_FILE

    selected_task = args.task.strip()
    if not selected_task:
        selected_task = os.environ.get("PASI_TASK", "").strip()
    if not selected_task and configured_task_file is not None:
        selected_task = load_task_file(configured_task_file)
    if not selected_task:
        selected_task = DEFAULT_ENGINEERING_TASK
    selected_task = DIFFICULT_MODE_PREFIX + "\n" + selected_task

    sys.argv = [
        "pasi_overnight_engine_v2.py",
        "--hours",
        str(hours),
        "--task",
        selected_task,
        *passthrough,
    ]
    return supervisor.main()


if __name__ == "__main__":
    raise SystemExit(main())
