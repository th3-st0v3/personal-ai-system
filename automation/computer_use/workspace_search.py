from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .local_access import LocalAccessBroker


_TEXT_SUFFIXES = frozenset({
    ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".css", ".html", ".md",
    ".json", ".yaml", ".yml", ".toml", ".sh", ".sql", ".txt", ".ini", ".cfg",
})


@dataclass(frozen=True)
class WorkspaceSearch:
    """Search approved workspace roots without exposing sensitive files."""

    broker: LocalAccessBroker
    max_file_bytes: int = 500_000
    max_results: int = 50

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
        for root in self.broker.allowed_roots or ():
            for path in root.rglob("*"):
                if len(results) >= effective_limit:
                    return results
                if path.is_symlink() or not path.is_file() or path.suffix.casefold() not in _TEXT_SUFFIXES:
                    continue
                try:
                    resolved = path.resolve()
                except OSError:
                    continue
                if resolved in seen or not self.broker._under_allowed_root(resolved) or self.broker._is_sensitive(resolved):
                    continue
                seen.add(resolved)
                try:
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
