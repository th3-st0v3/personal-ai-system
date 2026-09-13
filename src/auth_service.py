"""Optional local account authentication for the beta web shell."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
from datetime import datetime, timezone

_SESSION_TTL_SECONDS = 60 * 60 * 24 * 30
_SESSIONS: dict[str, tuple[int, float]] = {}


def _columns(connection: sqlite3.Connection) -> set[str]:
    return {row[1] for row in connection.execute("PRAGMA table_info(users)").fetchall()}


def initialize(connection: sqlite3.Connection) -> None:
    connection.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE COLLATE NOCASE,
            display_name TEXT NOT NULL DEFAULT 'User',
            password_salt TEXT NOT NULL DEFAULT '',
            password_hash TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    columns = _columns(connection)
    migrations = {
        "display_name": "ALTER TABLE users ADD COLUMN display_name TEXT NOT NULL DEFAULT 'User'",
        "password_salt": "ALTER TABLE users ADD COLUMN password_salt TEXT NOT NULL DEFAULT ''",
        "password_hash": "ALTER TABLE users ADD COLUMN password_hash TEXT NOT NULL DEFAULT ''",
        "created_at": "ALTER TABLE users ADD COLUMN created_at TEXT NOT NULL DEFAULT ''",
    }
    for column, statement in migrations.items():
        if column not in columns:
            connection.execute(statement)
    connection.execute("UPDATE users SET display_name = COALESCE(NULLIF(display_name, ''), 'User')")
    connection.commit()


def _now() -> float:
    return datetime.now(timezone.utc).timestamp()


def _hash_password(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 180_000).hex()


def _require_credentials(email: str, password: str) -> tuple[str, str]:
    email = email.strip().casefold()
    if "@" not in email or len(email) < 5:
        raise ValueError("Enter a valid email address.")
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters.")
    return email, password


def signup(connection: sqlite3.Connection, email: str, password: str, display_name: str | None = None) -> dict[str, object]:
    initialize(connection)
    email, password = _require_credentials(email, password)
    name = (display_name or email.split("@", 1)[0]).strip() or "User"
    salt = secrets.token_bytes(16)
    try:
        cursor = connection.execute(
            "INSERT INTO users(email,display_name,password_salt,password_hash) VALUES(?,?,?,?)",
            (email, name[:80], salt.hex(), _hash_password(password, salt)),
        )
        connection.commit()
    except sqlite3.IntegrityError as exc:
        raise ValueError("An account with that email already exists.") from exc
    return {"id": cursor.lastrowid, "email": email, "display_name": name[:80]}


def login(connection: sqlite3.Connection, email: str, password: str) -> tuple[str, dict[str, object]]:
    initialize(connection)
    email, password = _require_credentials(email, password)
    row = connection.execute("SELECT id,email,display_name,password_salt,password_hash FROM users WHERE email=?", (email,)).fetchone()
    if row is None:
        raise ValueError("Email or password is incorrect.")
    try:
        valid = hmac.compare_digest(_hash_password(password, bytes.fromhex(row[3])), row[4])
    except (TypeError, ValueError):
        valid = False
    if not valid:
        raise ValueError("Email or password is incorrect.")
    token = secrets.token_urlsafe(32)
    _SESSIONS[token] = (int(row[0]), _now() + _SESSION_TTL_SECONDS)
    return token, {"id": row[0], "email": row[1], "display_name": row[2] or "User"}


def logout(token: str | None) -> None:
    if token:
        _SESSIONS.pop(token, None)


def current_user(connection: sqlite3.Connection, token: str | None) -> dict[str, object] | None:
    initialize(connection)
    if not token:
        return None
    session = _SESSIONS.get(token)
    if session is None:
        return None
    user_id, expiry = session
    if expiry <= _now():
        _SESSIONS.pop(token, None)
        return None
    row = connection.execute("SELECT id,email,display_name,created_at FROM users WHERE id=?", (user_id,)).fetchone()
    if row is None:
        _SESSIONS.pop(token, None)
        return None
    return {"id": row[0], "email": row[1], "display_name": row[2] or "User", "created_at": row[3]}


__all__ = ["initialize", "signup", "login", "logout", "current_user"]
