"""Shared account-to-resource authorization for the HTTP boundary."""
from __future__ import annotations

import sqlite3
from typing import Iterable

ActorId = int | str | None


def initialize(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS project_members (
            project_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            role TEXT NOT NULL DEFAULT 'owner',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (project_id, user_id),
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_project_members_user ON project_members(user_id, project_id);
        CREATE TABLE IF NOT EXISTS chat_members (
            chat_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            role TEXT NOT NULL DEFAULT 'owner',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (chat_id, user_id),
            FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_chat_members_user ON chat_members(user_id, chat_id);
        """
    )
    connection.commit()


def has_users(connection: sqlite3.Connection) -> bool:
    row = connection.execute("SELECT 1 FROM users LIMIT 1").fetchone()
    return row is not None


def _user_id(actor_id: ActorId) -> int | None:
    if actor_id is None or actor_id == "local":
        return None
    try:
        return int(actor_id)
    except (TypeError, ValueError) as exc:
        raise PermissionError("Authentication required.") from exc


def require_authenticated(connection: sqlite3.Connection, actor_id: ActorId) -> int | None:
    """Allow legacy local-only operation only while no accounts exist."""
    user_id = _user_id(actor_id)
    if user_id is None and has_users(connection):
        raise PermissionError("Authentication required.")
    return user_id


def project_allowed(connection: sqlite3.Connection, actor_id: ActorId, project_id: int) -> bool:
    user_id = _user_id(actor_id)
    if user_id is None:
        return not has_users(connection)
    row = connection.execute(
        "SELECT 1 FROM project_members WHERE project_id=? AND user_id=?",
        (project_id, user_id),
    ).fetchone()
    return row is not None


def require_project(connection: sqlite3.Connection, actor_id: ActorId, project_id: int) -> None:
    if not project_allowed(connection, actor_id, project_id):
        raise PermissionError("Project access denied.")


def chat_allowed(connection: sqlite3.Connection, actor_id: ActorId, chat_id: int) -> bool:
    user_id = _user_id(actor_id)
    if user_id is None:
        return not has_users(connection)
    row = connection.execute(
        """
        SELECT 1
        FROM chat_members cm
        WHERE cm.chat_id=? AND cm.user_id=?
        UNION
        SELECT 1
        FROM chats c
        JOIN project_members pm ON pm.project_id=c.project_id
        WHERE c.id=? AND pm.user_id=?
        LIMIT 1
        """,
        (chat_id, user_id, chat_id, user_id),
    ).fetchone()
    return row is not None


def require_chat(connection: sqlite3.Connection, actor_id: ActorId, chat_id: int) -> None:
    if not chat_allowed(connection, actor_id, chat_id):
        raise PermissionError("Chat access denied.")


def claim_project(connection: sqlite3.Connection, project_id: int, user_id: int) -> None:
    connection.execute(
        "INSERT OR IGNORE INTO project_members(project_id,user_id,role) VALUES(?,?,?)",
        (project_id, user_id, "owner"),
    )
    connection.commit()


def claim_chat(connection: sqlite3.Connection, chat_id: int, user_id: int) -> None:
    connection.execute(
        "INSERT OR IGNORE INTO chat_members(chat_id,user_id,role) VALUES(?,?,?)",
        (chat_id, user_id, "owner"),
    )
    connection.commit()


def claim_legacy_data(connection: sqlite3.Connection, user_id: int) -> None:
    """Assign pre-account local data to the first account created in the beta."""
    connection.execute(
        "INSERT OR IGNORE INTO project_members(project_id,user_id,role) "
        "SELECT p.id, ?, 'owner' FROM projects p "
        "WHERE NOT EXISTS (SELECT 1 FROM project_members pm WHERE pm.project_id=p.id)",
        (user_id,),
    )
    connection.execute(
        "INSERT OR IGNORE INTO chat_members(chat_id,user_id,role) "
        "SELECT c.id, ?, 'owner' FROM chats c "
        "WHERE NOT EXISTS (SELECT 1 FROM chat_members cm WHERE cm.chat_id=c.id)",
        (user_id,),
    )
    connection.commit()


def owned_project_ids(connection: sqlite3.Connection, actor_id: ActorId) -> set[int] | None:
    user_id = _user_id(actor_id)
    if user_id is None:
        return None if not has_users(connection) else set()
    rows = connection.execute(
        "SELECT project_id FROM project_members WHERE user_id=?",
        (user_id,),
    ).fetchall()
    return {int(row[0]) for row in rows}


def owned_chat_ids(connection: sqlite3.Connection, actor_id: ActorId) -> set[int] | None:
    user_id = _user_id(actor_id)
    if user_id is None:
        return None if not has_users(connection) else set()
    rows = connection.execute(
        """
        SELECT c.id
        FROM chats c
        JOIN chat_members cm ON cm.chat_id=c.id
        WHERE cm.user_id=?
        UNION
        SELECT c.id
        FROM chats c
        JOIN project_members pm ON pm.project_id=c.project_id
        WHERE pm.user_id=?
        """,
        (user_id, user_id),
    ).fetchall()
    return {int(row[0]) for row in rows}


def filter_rows(rows: Iterable[dict[str, object]], allowed_ids: set[int] | None, key: str = "id") -> list[dict[str, object]]:
    if allowed_ids is None:
        return list(rows)
    filtered: list[dict[str, object]] = []
    for row in rows:
        raw_id = row.get(key)
        if isinstance(raw_id, bool):
            continue
        try:
            row_id = int(raw_id) if isinstance(raw_id, (int, str, float)) else None
        except (TypeError, ValueError):
            row_id = None
        if row_id is not None and row_id in allowed_ids:
            filtered.append(row)
    return filtered


__all__ = [
    "ActorId", "initialize", "has_users", "require_authenticated", "project_allowed",
    "require_project", "chat_allowed", "require_chat", "claim_project", "claim_chat",
    "claim_legacy_data", "owned_project_ids", "owned_chat_ids", "filter_rows",
]
