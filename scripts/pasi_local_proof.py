#!/usr/bin/env python3
"""Fast local proofing for staged or all tracked PASI source files."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXTENSIONS = {
    ".py": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".sh": "shell",
    ".json": "json",
}


def tracked_files(all_files: bool) -> list[str]:
    if all_files:
        command = ["git", "-C", str(ROOT), "ls-files"]
    else:
        command = [
            "git",
            "-C",
            str(ROOT),
            "diff",
            "--cached",
            "--name-only",
            "--diff-filter=ACMR",
        ]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    return [
        value.strip()
        for value in result.stdout.splitlines()
        if value.strip() and Path(value).suffix in EXTENSIONS
    ]


def run(command: list[str]) -> None:
    subprocess.run(command, cwd=ROOT, check=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--staged", action="store_true")
    group.add_argument("--all", action="store_true")
    args = parser.parse_args()

    files = tracked_files(args.all)
    if not files:
        print("PASI local proofing: no relevant files to check.")
        return 0

    by_kind: dict[str, list[str]] = {}
    for file in files:
        by_kind.setdefault(EXTENSIONS[Path(file).suffix], []).append(file)

    for file in by_kind.get("python", []):
        run([sys.executable, "-m", "py_compile", file])

    node = shutil_which("node")
    if by_kind.get("javascript"):
        if not node:
            raise SystemExit("node is required to proof JavaScript files")
        for file in by_kind["javascript"]:
            run([node, "--check", file])

    for file in by_kind.get("shell", []):
        run(["bash", "-n", file])

    for file in by_kind.get("json", []):
        run([sys.executable, "-c", "import json, pathlib; json.load(pathlib.Path(__import__('sys').argv[1]).open(encoding='utf-8'))", file])

    print(
        "PASI local proofing: PASS "
        f"(python={len(by_kind.get('python', []))}, "
        f"javascript={len(by_kind.get('javascript', []))}, "
        f"shell={len(by_kind.get('shell', []))}, "
        f"json={len(by_kind.get('json', []))})"
    )
    return 0


def shutil_which(command: str) -> str | None:
    import shutil

    return shutil.which(command)


if __name__ == "__main__":
    raise SystemExit(main())
