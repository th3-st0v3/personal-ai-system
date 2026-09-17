from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .local_access import LocalAccessBroker, LocalAccessError


STATE_RELATIVE_PATH = ".runtime/computer/vscode-state.json"
MAX_STATE_CHARS = 100_000
MAX_AGE_SECONDS = 30.0


@dataclass(frozen=True)
class VSCodeStateReader:
    """Read the small state document published by the optional PASI VS Code extension."""

    broker: LocalAccessBroker
    max_age_seconds: float = MAX_AGE_SECONDS

    def read(self) -> dict[str, Any]:
        if self.max_age_seconds <= 0:
            raise ValueError("max_age_seconds must be positive")
        try:
            result = self.broker.read_text(STATE_RELATIVE_PATH, max_chars=MAX_STATE_CHARS)
        except LocalAccessError as exc:
            return {"status": "unavailable", "error": str(exc)}

        try:
            payload = json.loads(result["content"])
        except (TypeError, json.JSONDecodeError):
            return {"status": "invalid", "error": "VS Code state document is not valid JSON"}
        if not isinstance(payload, dict):
            return {"status": "invalid", "error": "VS Code state document must be an object"}
        if payload.get("schema_version") != "pasi-vscode-readonly-v1":
            return {"status": "invalid", "error": "unsupported VS Code state schema"}

        captured_at = payload.get("captured_at")
        if not isinstance(captured_at, str):
            return {"status": "invalid", "error": "VS Code state timestamp is missing"}
        try:
            stamp = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
        except ValueError:
            return {"status": "invalid", "error": "VS Code state timestamp is invalid"}
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - stamp).total_seconds()
        if age < -5.0 or age > self.max_age_seconds:
            return {"status": "stale", "age_seconds": round(age, 3), "captured_at": captured_at}

        return {
            "status": "ok",
            "age_seconds": round(max(0.0, age), 3),
            "captured_at": captured_at,
            "workspace": self._bounded_workspace(payload.get("workspace")),
            "active_editor": self._bounded_editor(payload.get("active_editor")),
            "visible_editors": self._bounded_editors(payload.get("visible_editors")),
            "diagnostics": self._bounded_diagnostics(payload.get("diagnostics")),
        }

    @staticmethod
    def _bounded_workspace(value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {}
        folders = value.get("folders", [])
        names = [str(item)[:200] for item in folders if isinstance(item, str)][:20] if isinstance(folders, list) else []
        return {"name": str(value.get("name", ""))[:200], "folders": names}

    @staticmethod
    def _bounded_editor(value: Any) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None
        return {
            "path": str(value.get("path", ""))[:500],
            "language": str(value.get("language", ""))[:100],
            "dirty": bool(value.get("dirty", False)),
            "line": int(value.get("line", 0)) if isinstance(value.get("line"), int) else 0,
        }

    @classmethod
    def _bounded_editors(cls, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        return [editor for item in value[:20] if isinstance((editor := cls._bounded_editor(item)), dict)]

    @staticmethod
    def _bounded_diagnostics(value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {"errors": 0, "warnings": 0, "information": 0, "hints": 0}
        return {
            "errors": max(0, int(value.get("errors", 0))) if isinstance(value.get("errors"), int) else 0,
            "warnings": max(0, int(value.get("warnings", 0))) if isinstance(value.get("warnings"), int) else 0,
            "information": max(0, int(value.get("information", 0))) if isinstance(value.get("information"), int) else 0,
            "hints": max(0, int(value.get("hints", 0))) if isinstance(value.get("hints"), int) else 0,
        }
