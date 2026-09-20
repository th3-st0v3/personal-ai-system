from __future__ import annotations

import hashlib
import json
import re
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .state_paths import resolve_state_root
from typing import Any, Mapping

MAX_DETAIL_CHARS = 4_000
MAX_OBSTACLE_LOG_BYTES = 2_000_000
MAX_RECENT_LINES = 200
MAX_COMPACT_LINES = 500
MAX_PENDING_COMPACT = 200
_PENDING_STATUSES = frozenset({"pending", "needs_preapproval", "waiting_external"})
_REDACT_RE = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._-]+|(api[_ -]?key\s*[=:]\s*|token\s*[=:]\s*|password\s*[=:]\s*)\S+")
_SENSITIVE_KEYS = re.compile(r"(?i)(api[_ -]?key|access[_ -]?token|refresh[_ -]?token|password|secret|authorization|credential|private[_ -]?key)")


@dataclass(frozen=True)
class Obstacle:
    obstacle_id: str
    created_at: str
    kind: str
    status: str
    summary: str
    next_action: str
    task_id: str = ""
    details: Mapping[str, Any] = field(default_factory=dict)
    fingerprint: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "obstacle_id": self.obstacle_id,
            "created_at": self.created_at,
            "kind": self.kind,
            "status": self.status,
            "summary": self.summary,
            "next_action": self.next_action,
            "task_id": self.task_id,
            "details": dict(self.details),
            "fingerprint": self.fingerprint,
        }


def _redact(value: Any) -> Any:
    if isinstance(value, str):
        text = value[:MAX_DETAIL_CHARS]
        return _REDACT_RE.sub(lambda match: (match.group(1) or "") + "[redacted]", text)
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in list(value.items())[:50]:
            safe_key = str(key)
            result[safe_key] = "[redacted]" if _SENSITIVE_KEYS.search(safe_key) else _redact(item)
        return result
    if isinstance(value, list):
        return [_redact(item) for item in value[:50]]
    return value


@dataclass
class ObstacleLedger:
    repo_root: Path
    state_root: Path | None = None
    runtime_dir: Path = field(init=False)
    log_path: Path = field(init=False)
    list_path: Path = field(init=False)

    def __post_init__(self) -> None:
        self.repo_root = self.repo_root.expanduser().resolve()
        self.state_root = resolve_state_root(self.repo_root, self.state_root)
        self.runtime_dir = self.state_root / "automation"
        self.log_path = self.runtime_dir / "obstacles.jsonl"
        self.list_path = self.runtime_dir / "action-list.md"
        self.runtime_dir.mkdir(parents=True, exist_ok=True)

    def _fingerprint(self, kind: str, summary: str, next_action: str, task_id: str) -> str:
        payload = "\n".join((kind.strip().lower(), summary.strip().lower(), next_action.strip().lower(), task_id.strip().lower()))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]

    def _read_recent(self) -> list[dict[str, Any]]:
        try:
            with self.log_path.open("r", encoding="utf-8") as handle:
                lines = list(deque(handle, maxlen=MAX_RECENT_LINES))
        except OSError:
            return []
        values: list[dict[str, Any]] = []
        for line in lines:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                values.append(value)
        return values

    def _compact_if_needed(self, recent: list[dict[str, Any]]) -> None:
        try:
            oversized = self.log_path.stat().st_size > MAX_OBSTACLE_LOG_BYTES
        except OSError:
            oversized = False
        if not oversized:
            return

        pending: deque[dict[str, Any]] = deque(maxlen=MAX_PENDING_COMPACT)
        try:
            with self.log_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(item, dict) and item.get("status") in _PENDING_STATUSES:
                        pending.append(item)
        except OSError:
            pending.clear()

        merged: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in recent[-MAX_COMPACT_LINES:]:
            obstacle_id = str(item.get("obstacle_id", ""))
            fingerprint = str(item.get("fingerprint", ""))
            identity = obstacle_id or fingerprint or json.dumps(item, sort_keys=True, ensure_ascii=False)
            if identity in seen:
                continue
            seen.add(identity)
            merged.append(item)

        # Put retained pending obstacles at the end so _read_recent(), the action
        # list, and pending() continue to see them even after compaction.
        for item in pending:
            obstacle_id = str(item.get("obstacle_id", ""))
            fingerprint = str(item.get("fingerprint", ""))
            identity = obstacle_id or fingerprint or json.dumps(item, sort_keys=True, ensure_ascii=False)
            if identity in seen:
                continue
            seen.add(identity)
            merged.append(item)

        temporary = self.log_path.with_suffix(".jsonl.tmp")
        temporary.write_text(
            "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in merged[-MAX_COMPACT_LINES:]),
            encoding="utf-8",
        )
        temporary.replace(self.log_path)

    def record(
        self,
        kind: str,
        summary: str,
        next_action: str,
        *,
        task_id: str = "",
        status: str = "pending",
        details: Mapping[str, Any] | None = None,
    ) -> Obstacle:
        safe_summary = str(_redact(summary))[:MAX_DETAIL_CHARS]
        safe_next = str(_redact(next_action))[:MAX_DETAIL_CHARS]
        safe_details = _redact(dict(details or {}))
        fingerprint = self._fingerprint(kind, safe_summary, safe_next, task_id)
        recent = self._read_recent()
        for item in reversed(recent):
            if item.get("fingerprint") == fingerprint and item.get("status") in _PENDING_STATUSES:
                return Obstacle(
                    obstacle_id=str(item.get("obstacle_id", "")),
                    created_at=str(item.get("created_at", "")),
                    kind=str(item.get("kind", kind)),
                    status=str(item.get("status", status)),
                    summary=str(item.get("summary", safe_summary)),
                    next_action=str(item.get("next_action", safe_next)),
                    task_id=str(item.get("task_id", task_id)),
                    details=item.get("details", {}) if isinstance(item.get("details"), dict) else {},
                    fingerprint=fingerprint,
                )

        self._compact_if_needed(recent)
        created_at = datetime.now(timezone.utc).isoformat()
        obstacle_id = f"obs-{created_at.replace(':', '').replace('+00:00', 'Z')}-{fingerprint}"
        obstacle = Obstacle(
            obstacle_id=obstacle_id,
            created_at=created_at,
            kind=kind.strip() or "unknown",
            status=status.strip() or "pending",
            summary=safe_summary,
            next_action=safe_next,
            task_id=str(task_id)[:200],
            details=safe_details if isinstance(safe_details, Mapping) else {},
            fingerprint=fingerprint,
        )
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(obstacle.to_dict(), ensure_ascii=False) + "\n")
        self._refresh_action_list()
        return obstacle

    def _refresh_action_list(self) -> None:
        pending = [item for item in self._read_recent() if item.get("status") in _PENDING_STATUSES]
        lines = [
            "# PASI Action List",
            "",
            "This list is informational and non-blocking. PASI continues autonomous work while these obstacles remain unresolved.",
            "",
        ]
        if not pending:
            lines.append("- [x] No unresolved obstacles recorded.")
        else:
            for item in pending[-50:]:
                lines.append(f"- [ ] `{item.get('obstacle_id', 'unknown')}` **{item.get('kind', 'unknown')}** — {item.get('summary', '')}")
                lines.append(f"  Next action: {item.get('next_action', 'review obstacle')}")
        self.list_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def pending(self, limit: int = 50) -> list[dict[str, Any]]:
        values = [item for item in self._read_recent() if item.get("status") in _PENDING_STATUSES]
        return values[-max(1, limit):]
