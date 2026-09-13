"""Explicit authorization, rate limiting, and audit boundary for consequential actions."""
from __future__ import annotations

import sqlite3
import time

ACTIONS = {
    "read_project", "ingest_source", "run_calculation", "run_simulation",
    "modify_project_data", "execute_code", "remote_execution", "external_api_cost",
}
DEFAULT_SAFE_ACTIONS = {"read_project", "ingest_source", "run_calculation", "run_simulation"}
RATE_LIMITS = {
    "read_project": (120, 60), "ingest_source": (20, 60), "run_calculation": (120, 60),
    "run_simulation": (60, 60), "modify_project_data": (60, 60), "execute_code": (10, 60),
    "remote_execution": (5, 60), "external_api_cost": (5, 60),
}


def initialize(connection: sqlite3.Connection) -> None:
    """Create the authorization schema; safe to call repeatedly during migration/compatibility paths."""
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS permission_grants (
            actor_id TEXT NOT NULL,
            action TEXT NOT NULL,
            enabled INTEGER NOT NULL CHECK(enabled IN (0, 1)),
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY(actor_id, action)
        );
        CREATE TABLE IF NOT EXISTS action_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            actor_id TEXT NOT NULL,
            action TEXT NOT NULL,
            allowed INTEGER NOT NULL CHECK(allowed IN (0, 1)),
            reason TEXT,
            created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_action_audit_actor_action_time ON action_audit_log(actor_id, action, created_at);
    """)
    connection.commit()


def grant(connection: sqlite3.Connection, actor_id: str, action: str) -> None:
    validate_action(action)
    initialize(connection)
    actor_id = _actor(actor_id)
    connection.execute(
        "INSERT INTO permission_grants(actor_id, action, enabled) VALUES (?, ?, 1) "
        "ON CONFLICT(actor_id, action) DO UPDATE SET enabled=1, updated_at=datetime('now')",
        (actor_id, action),
    )
    connection.commit()


def revoke(connection: sqlite3.Connection, actor_id: str, action: str) -> None:
    validate_action(action)
    initialize(connection)
    connection.execute(
        "UPDATE permission_grants SET enabled=0, updated_at=datetime('now') WHERE actor_id=? AND action=?",
        (_actor(actor_id), action),
    )
    connection.commit()


def allowed(connection: sqlite3.Connection, actor_id: str, action: str) -> bool:
    validate_action(action)
    initialize(connection)
    actor_id = _actor(actor_id)
    row = connection.execute(
        "SELECT enabled FROM permission_grants WHERE actor_id=? AND action=?",
        (actor_id, action),
    ).fetchone()
    permitted = bool(row[0]) if row is not None else actor_id == "local" and action in DEFAULT_SAFE_ACTIONS
    _audit(connection, actor_id, action, permitted, None if permitted else "permission denied")
    return permitted


def require(connection: sqlite3.Connection, actor_id: str, action: str) -> None:
    actor_id = _actor(actor_id)
    if not allowed(connection, actor_id, action):
        raise PermissionError(f"Permission denied for action '{action}'.")
    _enforce_rate_limit(connection, actor_id, action)


def validate_action(action: str) -> None:
    if action not in ACTIONS:
        raise ValueError(f"Unknown action '{action}'.")


def _enforce_rate_limit(connection: sqlite3.Connection, actor_id: str, action: str) -> None:
    maximum, window_seconds = RATE_LIMITS[action]
    now = time.time()
    cutoff = now - window_seconds
    row = connection.execute(
        "SELECT COUNT(*) FROM action_audit_log WHERE actor_id=? AND action=? AND allowed=1 AND created_at>?",
        (actor_id, action, cutoff),
    ).fetchone()
    count = int(row[0]) if row else 0
    if count >= maximum:
        _audit(connection, actor_id, action, False, f"rate limit exceeded ({maximum}/{window_seconds}s)")
        raise PermissionError(f"Rate limit exceeded for action '{action}'. Try again later.")


def _audit(connection: sqlite3.Connection, actor_id: str, action: str, permitted: bool, reason: str | None) -> None:
    connection.execute(
        "INSERT INTO action_audit_log(actor_id, action, allowed, reason, created_at) VALUES (?, ?, ?, ?, ?)",
        (actor_id, action, 1 if permitted else 0, reason, time.time()),
    )
    connection.commit()


def purge_audit_log(connection: sqlite3.Connection, *, max_age_seconds: int = 30 * 24 * 60 * 60) -> int:
    initialize(connection)
    cursor = connection.execute("DELETE FROM action_audit_log WHERE created_at<?", (time.time() - max_age_seconds,))
    connection.commit()
    return cursor.rowcount


def _actor(actor_id: str) -> str:
    actor_id = str(actor_id).strip()
    if not actor_id or len(actor_id) > 128 or any(c in actor_id for c in "\r\n"):
        raise ValueError("actor_id must be a short non-empty identifier")
    return actor_id
