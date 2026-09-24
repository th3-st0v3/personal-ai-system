#!/usr/bin/env python3
"""Build a fail-closed public snapshot from the private PASI repository.

Only explicitly approved client-facing paths are copied. This intentionally does
not attempt to hide individual sensitive files inside the private repository;
instead it creates a separate publishable tree with none of the private
operator/backend history.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ALLOWED_PREFIXES = (
    "automation/chromium/pasi-chatgpt/",
    "automation/vscode/pasi-readonly/",
)

PUBLIC_FILES = {
    ".gitignore": """# Generated/runtime state
.runtime/
.venv/
__pycache__/
*.pyc
.env
.env.*
""",
    "README.md": """# Personal AI System — Public Surface

This repository is the public-facing client surface of Personal AI System.

It contains client-side automation and read-only editor integration that can be
shared publicly. The private development repository contains additional
operator, backend, planner, runner, and local-infrastructure components that
are intentionally not part of this snapshot.

## Included

- Chromium browser extension client
- Read-only VS Code integration

## Not included

- Private backend services
- Self-hosted runner bootstrap and control
- Long-running automation supervisor/engine
- Provider routing and private operator workflows
- Private roadmaps and internal development logs
- Local credentials, tokens, and runtime state

The public surface is not intended to be a complete standalone copy of the
private PASI system.
""",
    "SECURITY.md": """# Security Policy

Do not place credentials, tokens, browser profiles, private documents, or local
machine secrets in this repository.

The public surface is intentionally separated from PASI's private backend,
runner, and operator infrastructure. Reports about vulnerabilities in the
public surface should include reproduction steps without disclosing secrets.
""",
}

PUBLIC_CODEQL = """name: CodeQL

on:
  push:
    branches: [main]
  pull_request:
  workflow_dispatch:

permissions:
  contents: read
  security-events: write

jobs:
  analyze:
    name: CodeQL (${{ matrix.language }})
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        language: [javascript-typescript]
    steps:
      - name: Checkout
        uses: actions/checkout@v7

      - name: Initialize CodeQL
        uses: github/codeql-action/init@v4
        with:
          languages: ${{ matrix.language }}

      - name: Analyze
        uses: github/codeql-action/analyze@v4
        with:
          category: /language:${{ matrix.language }}
"""

def git_ls_files(root: Path) -> list[str]:
    proc = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return [item for item in proc.stdout.decode("utf-8").split("\0") if item]

def allowed(path: str) -> bool:
    normalized = path.replace("\\\\", "/")
    return any(normalized.startswith(prefix) for prefix in ALLOWED_PREFIXES)

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    root = Path(
        subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            text=True,
            cwd=Path.cwd(),
        ).strip()
    ).resolve()
    output = args.output.expanduser().resolve()

    if output == root or root in output.parents:
        raise SystemExit("Refusing to write a public snapshot inside the private repository.")

    if output.exists() and any(output.iterdir()):
        raise SystemExit(f"Output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)

    copied = 0
    for rel in git_ls_files(root):
        if not allowed(rel):
            continue
        source = root / rel
        destination = output / rel
        if not source.is_file():
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        copied += 1

    for rel, content in PUBLIC_FILES.items():
        dest = output / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content.rstrip() + "\n", encoding="utf-8")

    workflow = output / ".github" / "workflows" / "codeql.yml"
    workflow.parent.mkdir(parents=True, exist_ok=True)
    workflow.write_text(PUBLIC_CODEQL, encoding="utf-8")

    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    (output / "PUBLIC_SNAPSHOT.md").write_text(
        "# Public Snapshot\n\n"
        f"Generated from private PASI at commit {commit}.\n\n"
        f"Copied {copied} explicitly allowlisted tracked files.\n"
        "No private backend, runner, planner, roadmap, or operator path is exported.\n",
        encoding="utf-8",
    )

    print(f"Public snapshot ready: {output}")
    print(f"Copied allowlisted tracked files: {copied}")
    print("Fail-closed allowlist: automation/chromium/pasi-chatgpt + automation/vscode/pasi-readonly")
    return 0

if __name__ == "__main__":
    sys.exit(main())
