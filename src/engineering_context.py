"""Bounded, secret-aware repository context for the supervised build assistant."""
from __future__ import annotations

from pathlib import Path

IGNORED_PARTS = {".git", ".venv", "venv", "node_modules", ".runtime", "__pycache__", "build", "dist"}
SECRET_NAMES = {".env", ".env.local", ".env.production", "credentials.json"}
SECRET_SUFFIXES = {".key", ".pem", ".p12", ".pfx"}
TEXT_SUFFIXES = {".py", ".js", ".ts", ".tsx", ".html", ".css", ".md", ".toml", ".yaml", ".yml", ".json", ".txt", ".sql", ".sh"}
DEFAULT_MAX_FILE_CHARS = 8_000


def collect_context(
    root: Path,
    *,
    max_chars: int = 80_000,
    max_file_chars: int = DEFAULT_MAX_FILE_CHARS,
) -> str:
    root = Path(root).resolve()
    if not root.is_dir():
        raise ValueError(f"Repository path does not exist: {root}")
    if max_chars < 1 or max_file_chars < 1:
        raise ValueError("max_chars and max_file_chars must be positive")

    files = []
    total = 0
    for path in sorted(root.rglob("*")):
        if (
            not path.is_file()
            or _ignored(path, root)
            or path.name in SECRET_NAMES
            or path.suffix.lower() in SECRET_SUFFIXES
            or path.suffix.lower() not in TEXT_SUFFIXES
        ):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        text = text[:max_file_chars]
        remaining = max_chars - total
        if remaining <= 0:
            break
        text = text[:remaining]
        relative = path.relative_to(root).as_posix()
        files.append(f"FILE: {relative}\n{text}")
        total += len(text)
    return "\n\n".join(files)


def _ignored(path: Path, root: Path) -> bool:
    try:
        return bool(IGNORED_PARTS.intersection(path.relative_to(root).parts))
    except ValueError:
        return True


__all__ = ["collect_context"]
