from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping

from .contracts import Observation


_ALLOWED_SEVERITIES = frozenset({"error", "warning", "information", "hint", "unknown"})
_DEFAULT_IGNORED_DIRECTORIES = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "env",
        ".tox",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "node_modules",
        "dist",
        "build",
        "__pycache__",
    }
)


class VSCodeEvidenceError(ValueError):
    """Raised when a read-only VS Code evidence request is invalid."""


@dataclass(frozen=True, order=True)
class Diagnostic:
    """Normalized language-server/editor diagnostic."""

    path: str
    line: int
    column: int
    severity: str
    message: str
    source: str | None = None
    end_line: int | None = None
    end_column: int | None = None
    code: str | int | None = None

    def __post_init__(self) -> None:
        if not self.path.strip() or self.line < 1 or self.column < 1:
            raise VSCodeEvidenceError("diagnostic path/position is invalid")
        if self.severity not in _ALLOWED_SEVERITIES:
            raise VSCodeEvidenceError(f"unsupported diagnostic severity: {self.severity!r}")
        if not self.message.strip():
            raise VSCodeEvidenceError("diagnostic message is required")
        if self.end_line is not None and self.end_line < self.line:
            raise VSCodeEvidenceError("end_line cannot precede line")
        if self.end_column is not None and self.end_column < 1:
            raise VSCodeEvidenceError("end_column must be positive")

    def canonical(self) -> dict[str, Any]:
        return asdict(self)

    def fingerprint(self) -> str:
        payload = json.dumps(self.canonical(), sort_keys=True, separators=(",", ":"))
        return sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class VSCodeEvidenceAdapter:
    """Read-only workspace evidence adapter for VS Code-integrated tooling.

    The adapter does not drive VS Code, invoke a shell, or mutate the workspace.
    A companion process/extension can publish diagnostics and editor state as JSON;
    the adapter consumes those snapshots as evidence.
    """

    workspace_root: str
    diagnostics_path: str | None = None
    state_path: str | None = None
    max_file_bytes: int = 256 * 1024
    max_search_results: int = 100
    max_search_query_length: int = 200

    def __post_init__(self) -> None:
        root = self._root()
        if not root.exists() or not root.is_dir():
            raise VSCodeEvidenceError("workspace_root must be an existing directory")
        if self.max_file_bytes <= 0 or self.max_search_results <= 0:
            raise VSCodeEvidenceError("adapter bounds must be positive")
        if self.max_search_query_length <= 0:
            raise VSCodeEvidenceError("max_search_query_length must be positive")

    def observe(self) -> Observation:
        state: dict[str, Any] = {
            "workspace_root": str(self._root()),
            "files": self._file_inventory(),
        }
        if self.state_path is not None:
            state.update(self._load_state())
        state["inventory_fingerprint"] = self._stable_fingerprint(state)
        return Observation(
            observation_id="vscode-workspace",
            session_id="unspecified",
            source="vscode",
            kind="workspace",
            data=state,
        )

    def read_file(self, path: str) -> Observation:
        resolved, relative = self._resolve_relative_file(path)
        size = resolved.stat().st_size
        if size > self.max_file_bytes:
            raise VSCodeEvidenceError(
                f"file exceeds max_file_bytes ({self.max_file_bytes})"
            )
        try:
            text = resolved.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise VSCodeEvidenceError("file is not valid UTF-8 text") from exc
        return Observation(
            observation_id=f"vscode-file:{relative}",
            session_id="unspecified",
            source="vscode",
            kind="file",
            data={
                "path": relative,
                "size_bytes": size,
                "text": text,
                "fingerprint": sha256(text.encode("utf-8")).hexdigest(),
            },
        )

    def search(self, query: str) -> Observation:
        if not query.strip():
            raise VSCodeEvidenceError("search query must not be empty")
        if len(query) > self.max_search_query_length:
            raise VSCodeEvidenceError("search query exceeds configured bound")

        matches: list[dict[str, Any]] = []
        for path in self._iter_text_files():
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for line_number, line in enumerate(text.splitlines(), start=1):
                if query.casefold() in line.casefold():
                    matches.append(
                        {
                            "path": path.relative_to(self._root()).as_posix(),
                            "line": line_number,
                            "text": line[:2000],
                        }
                    )
                    if len(matches) >= self.max_search_results:
                        break
            if len(matches) >= self.max_search_results:
                break

        return Observation(
            observation_id=f"vscode-search:{sha256(query.encode('utf-8')).hexdigest()[:16]}",
            session_id="unspecified",
            source="vscode",
            kind="search",
            data={
                "query": query,
                "matches": matches,
                "truncated": len(matches) >= self.max_search_results,
                "fingerprint": self._stable_fingerprint(matches),
            },
        )

    def diagnostics(self) -> Observation:
        diagnostics = self._load_diagnostics()
        normalized = [item.canonical() for item in diagnostics]
        return Observation(
            observation_id="vscode-diagnostics",
            session_id="unspecified",
            source="vscode",
            kind="diagnostics",
            data={
                "diagnostics": normalized,
                "count": len(normalized),
                "fingerprint": self._stable_fingerprint(normalized),
            },
        )

    def _root(self) -> Path:
        return Path(self.workspace_root).expanduser().resolve()

    def _resolve_relative_file(self, path: str) -> tuple[Path, str]:
        candidate = Path(path)
        if candidate.is_absolute():
            raise VSCodeEvidenceError("file paths must be workspace-relative")
        if ".." in candidate.parts:
            raise VSCodeEvidenceError("file path escapes workspace root")
        relative = candidate.as_posix()
        if not relative or relative == ".":
            raise VSCodeEvidenceError("file path is required")
        resolved = (self._root() / candidate).resolve()
        try:
            resolved.relative_to(self._root())
        except ValueError as exc:
            raise VSCodeEvidenceError("file path escapes workspace root") from exc
        if not resolved.is_file():
            raise VSCodeEvidenceError("file does not exist")
        return resolved, relative

    def _iter_text_files(self):
        root = self._root()
        for current, directories, filenames in os.walk(root):
            directories[:] = sorted(
                name for name in directories if name not in _DEFAULT_IGNORED_DIRECTORIES
            )
            for filename in sorted(filenames):
                path = Path(current) / filename
                try:
                    if path.stat().st_size <= self.max_file_bytes:
                        yield path
                except OSError:
                    continue

    def _file_inventory(self) -> list[str]:
        return sorted(path.relative_to(self._root()).as_posix() for path in self._iter_text_files())

    def _load_json(self, path: str) -> Mapping[str, Any]:
        resolved, _ = self._resolve_relative_file(path)
        try:
            value = json.loads(resolved.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise VSCodeEvidenceError(f"invalid JSON evidence file: {path}") from exc
        if not isinstance(value, Mapping):
            raise VSCodeEvidenceError("JSON evidence root must be an object")
        return value

    def _load_state(self) -> dict[str, Any]:
        assert self.state_path is not None
        raw = self._load_json(self.state_path)
        allowed = {"active_file", "open_files", "workspace_name"}
        return {key: raw[key] for key in sorted(raw) if key in allowed}

    def _load_diagnostics(self) -> list[Diagnostic]:
        if self.diagnostics_path is None:
            return []
        raw = self._load_json(self.diagnostics_path)
        items = raw.get("diagnostics", [])
        if not isinstance(items, list):
            raise VSCodeEvidenceError("diagnostics must be a list")
        diagnostics: list[Diagnostic] = []
        for item in items:
            if not isinstance(item, Mapping):
                raise VSCodeEvidenceError("diagnostic entries must be objects")
            diagnostic = Diagnostic(
                path=str(item.get("path", "")),
                line=int(item.get("line", 0)),
                column=int(item.get("column", 0)),
                severity=str(item.get("severity", "unknown")).lower(),
                message=str(item.get("message", "")),
                source=None if item.get("source") is None else str(item["source"]),
                end_line=None if item.get("end_line") is None else int(item["end_line"]),
                end_column=None
                if item.get("end_column") is None
                else int(item["end_column"]),
                code=item.get("code"),
            )
            self._resolve_relative_file(diagnostic.path)
            diagnostics.append(diagnostic)
        diagnostics.sort(
            key=lambda item: (
                item.path,
                item.line,
                item.column,
                item.severity,
                item.message,
                item.source or "",
                str(item.code) if item.code is not None else "",
            )
        )
        return diagnostics

    @staticmethod
    def _stable_fingerprint(value: Any) -> str:
        payload = json.dumps(value, sort_keys=True, separators=(",", ":"))
        return sha256(payload.encode("utf-8")).hexdigest()
