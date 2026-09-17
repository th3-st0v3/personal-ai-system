#!/usr/bin/env python3
"""Build a bounded, secret-aware text snapshot of the repository for AI review."""
from __future__ import annotations

import fnmatch
from pathlib import Path

DEFAULT_MAX_CHARS = 80_000
DEFAULT_MAX_FILE_CHARS = 8_000
SKIP_DIRS = {".git", ".runtime", "__pycache__", ".venv", "venv", "node_modules"}
SECRET_PATTERNS = ("*.pem", "*.key", "*.p12", "*.pfx", ".env", ".env.*", "*secret*", "*credential*")
TEXT_SUFFIXES = {".py", ".js", ".css", ".html", ".md", ".json", ".yaml", ".yml", ".toml", ".sh", ".sql", ".txt"}


def is_secret(path: Path) -> bool:
    name = path.name.lower()
    return any(fnmatch.fnmatch(name, pattern) for pattern in SECRET_PATTERNS)


def collect_context(root: Path, *, max_chars: int = DEFAULT_MAX_CHARS, max_file_chars: int = DEFAULT_MAX_FILE_CHARS) -> str:
    root = root.resolve()
    if not root.is_dir():
        raise ValueError(f"Repository path is not a directory: {root}")
    chunks: list[str] = [f"Repository: {root.name}", "Files:"]
    files = []
    for path in root.rglob("*"):
        if not path.is_file() or is_secret(path) or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        files.append(path)
    for path in sorted(files):
        relative = path.relative_to(root).as_posix()
        chunks.append(f"FILE: {relative}")
    chunks.append("\nContent samples:")
    used = sum(len(chunk) + 1 for chunk in chunks)
    for path in sorted(files):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        excerpt = text[:max_file_chars]
        block = f"\n### {path.relative_to(root).as_posix()}\n{excerpt}"
        if used + len(block) > max_chars:
            break
        chunks.append(block)
        used += len(block)
    return "\n".join(chunks)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Print a bounded repository context snapshot.")
    parser.add_argument("root", nargs="?", default=".")
    parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)
    args = parser.parse_args()
    print(collect_context(Path(args.root), max_chars=args.max_chars))
