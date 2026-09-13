"""Registry for provider connections and frontier-AI tool plugins.

The beta keeps registration declarative and explicit. Credentials and network
side effects belong to provider implementations, not the registry itself.
"""
from __future__ import annotations

import json
import sqlite3


def _lastrowid(cursor: sqlite3.Cursor) -> int:
    row_id = cursor.lastrowid
    if row_id is None:
        raise RuntimeError("SQLite did not return a row ID.")
    return int(row_id)


def initialize(connection: sqlite3.Connection) -> None:
    connection.executescript("""
    CREATE TABLE IF NOT EXISTS connections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        provider TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'disconnected',
        capabilities TEXT NOT NULL DEFAULT '[]',
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS plugins (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        version TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        entrypoint TEXT NOT NULL,
        capabilities TEXT NOT NULL DEFAULT '[]',
        enabled INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    """)
    connection.commit()


def register_connection(
    connection: sqlite3.Connection,
    name: str,
    provider: str,
    capabilities: list[str] | None = None,
) -> int:
    cursor = connection.execute(
        "INSERT INTO connections(name,provider,capabilities) VALUES(?,?,?)",
        (name.strip(), provider.strip(), json.dumps(capabilities or [])),
    )
    connection.commit()
    return _lastrowid(cursor)


def list_connections(connection: sqlite3.Connection) -> list[dict[str, object]]:
    rows = connection.execute(
        "SELECT id,name,provider,status,capabilities,created_at,updated_at "
        "FROM connections ORDER BY name COLLATE NOCASE"
    ).fetchall()
    return [
        {
            "id": r[0],
            "name": r[1],
            "provider": r[2],
            "status": r[3],
            "capabilities": json.loads(r[4]),
            "created_at": r[5],
            "updated_at": r[6],
        }
        for r in rows
    ]


def register_plugin(
    connection: sqlite3.Connection,
    name: str,
    version: str,
    description: str,
    entrypoint: str,
    capabilities: list[str] | None = None,
) -> int:
    cursor = connection.execute(
        "INSERT INTO plugins(name,version,description,entrypoint,capabilities) "
        "VALUES(?,?,?,?,?)",
        (
            name.strip(),
            version.strip(),
            description.strip(),
            entrypoint.strip(),
            json.dumps(capabilities or []),
        ),
    )
    connection.commit()
    return _lastrowid(cursor)


def list_plugins(connection: sqlite3.Connection) -> list[dict[str, object]]:
    rows = connection.execute(
        "SELECT id,name,version,description,entrypoint,capabilities,enabled,created_at "
        "FROM plugins ORDER BY name COLLATE NOCASE"
    ).fetchall()
    return [
        {
            "id": r[0],
            "name": r[1],
            "version": r[2],
            "description": r[3],
            "entrypoint": r[4],
            "capabilities": json.loads(r[5]),
            "enabled": bool(r[6]),
            "created_at": r[7],
        }
        for r in rows
    ]


def set_plugin_enabled(
    connection: sqlite3.Connection,
    plugin_id: int,
    enabled: bool,
) -> dict[str, object]:
    cursor = connection.execute(
        "UPDATE plugins SET enabled=? WHERE id=?",
        (int(enabled), plugin_id),
    )
    if cursor.rowcount != 1:
        raise ValueError("Plugin not found.")
    connection.commit()
    plugin = next(
        (item for item in list_plugins(connection) if item["id"] == plugin_id),
        None,
    )
    if plugin is None:
        raise RuntimeError("Plugin disappeared after update.")
    return plugin


__all__ = [
    "initialize",
    "register_connection",
    "list_connections",
    "register_plugin",
    "list_plugins",
    "set_plugin_enabled",
]
