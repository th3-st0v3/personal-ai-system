from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .local_access import LocalAccessBroker


_TEXT_SUFFIXES = frozenset({
    ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".css", ".html", ".md",
    ".json", ".yaml", ".yml", ".toml", ".sh", ".sql", ".txt", ".ini", ".cfg",
})
_PRUNED_DIRS = frozenset({
    ".git", ".venv", "venv", "env", "node_modules", "__pycache__", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", ".pyright", ".cache", ".next", ".turbo", ".parcel-cache",
    ".runtime", "dist", "build", "coverage", "htmlcov", "generated", "artifacts", "tmp",
    "site-packages", "vendor", "third_party",
})


@dataclass(frozen=True)
class WorkspaceSearch:
    """Search approved workspace roots without exposing sensitive files."""

    broker: LocalAccessBroker
    max_file_bytes: int = 500_000
    max_results: int = 50
    max_files_scanned: int = 2_000

    def __post_init__(self) -> None:
        if self.max_file_bytes <= 0 or self.max_results <= 0 or self.max_files_scanned <= 0:
            raise ValueError("workspace search bounds must be positive")

    def search(self, query: str, *, limit: int | None = None) -> list[dict[str, Any]]:
        query = str(query or "").strip()
        if not query or len(query) > 200:
            raise ValueError("search query must be non-empty and at most 200 characters")
        effective_limit = self.max_results if limit is None else limit
        if not 1 <= effective_limit <= self.max_results:
            raise ValueError(f"search result limit must be between 1 and {self.max_results}")

        needle = query.casefold()
        results: list[dict[str, Any]] = []
        seen: set[Path] = set()
        scanned = 0
        for root in self.broker.allowed_roots or ():
            for directory, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
                dirnames[:] = [name for name in dirnames if name not in _PRUNED_DIRS]
                for name in filenames:
                    if len(results) >= effective_limit or scanned >= self.max_files_scanned:
                        return results
                    path = Path(directory) / name
                    scanned += 1
                    if path.is_symlink() or path.suffix.casefold() not in _TEXT_SUFFIXES:
                        continue
                    try:
                        resolved = path.resolve()
                        if resolved in seen or not self.broker._under_allowed_root(resolved) or self.broker._is_sensitive(resolved):
                            continue
                        seen.add(resolved)
                        if resolved.stat().st_size > self.max_file_bytes:
                            continue
                        text = resolved.read_text(encoding="utf-8")
                    except (OSError, UnicodeDecodeError):
                        continue
                    lower = text.casefold()
                    start = 0
                    while len(results) < effective_limit:
                        index = lower.find(needle, start)
                        if index < 0:
                            break
                        line_start = text.rfind("\n", 0, index) + 1
                        line_end = text.find("\n", index)
                        if line_end < 0:
                            line_end = len(text)
                        results.append({
                            "path": str(resolved),
                            "line": text.count("\n", 0, index) + 1,
                            "snippet": text[line_start:line_end][:500],
                        })
                        start = max(index + len(query), index + 1)
        return results
