#!/usr/bin/env python3
"""Run PASI's bounded changed-file validation gate against a Git comparison base."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import pasi_overnight_engine_v2 as engine


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the same bounded gate PASI uses for autonomous task progression."
    )
    parser.add_argument(
        "--base-ref",
        required=True,
        help="Git ref used as the three-dot comparison base.",
    )
    args = parser.parse_args()

    root = Path.cwd().resolve()
    base_ref = args.base_ref.strip()
    if not base_ref:
        print("--base-ref must not be empty", file=sys.stderr)
        return 2

    verify = subprocess.run(
        ["git", "rev-parse", "--verify", f"{base_ref}^{{commit}}"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if verify.returncode != 0:
        print(f"validation base is not available: {base_ref}", file=sys.stderr)
        print(verify.stderr.strip(), file=sys.stderr)
        return 2

    try:
        result = engine.fast_local_gate(root, diff_base=base_ref)
    except Exception as exc:
        print(f"PASI fast validation failed: {exc}", file=sys.stderr)
        return 1

    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
