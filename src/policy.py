"""Small, explicit authorization layer for consequential engineering actions."""
from __future__ import annotations

import sqlite3

ACTIONS = {
    "read_project", "ingest_source", "run_calculation", "run_simulation",
    "modify_project_data", "execute_code", "remote_execution", "external_api_cost",
}
DEFAULT_SAFE_ACTIONS = {"read_project", "ingest_source", "run_calculation"}


def initialize(connection: sqlite3.Connection) -> None:
    connection.execute("""
        CREATE TABLE IF NOT EXISTS permission_grants (
            actor_id TEXT NOT NULL,
            action TEXT NOT NULL,
            enabled INTEGER NOT NULL CHECK(enabled IN (0, 1)),
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY(actor_id, action)
        )
    """)
    connection.commit()


def grant(connection: sqlite3.Connection, actor_id: str, action: str) -> None:
    validate_action(action)
    actor_id = _actor(actor_id)
    initialize(connection)
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
    actor_id = _actor(actor_id)
    initialize(connection)
    row = connection.execute(
        "SELECT enabled FROM permission_grants WHERE actor_id=? AND action=?",
        (actor_id, action),
    ).fetchone()
    if row is not None:
        return bool(row[0])
    return actor_id == "local" and action in DEFAULT_SAFE_ACTIONS


def require(connection: sqlite3.Connection, actor_id: str, action: str) -> None:
    if not allowed(connection, actor_id, action):
        raise PermissionError(f"Permission denied for action '{action}'.")


def validate_action(action: str) -> None:
    if action not in ACTIONS:
        raise ValueError(f"Unknown action '{action}'.")


def _actor(actor_id: str) -> str:
    actor_id = str(actor_id).strip()
    if not actor_id or len(actor_id) > 128 or any(c in actor_id for c in "\r\n"):
        raise ValueError("actor_id must be a short non-empty identifier")
    return actor_id
