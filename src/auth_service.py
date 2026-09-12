"""Optional local account authentication for the beta web shell.

Accounts are useful for personalization without making login a prerequisite for
using the local engineering workspace. Passwords are stored as salted PBKDF2
verifiers; session tokens remain process-local in this beta implementation.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
from datetime import datetime, timezone


_SESSION_TTL_SECONDS = 60 * 60 * 24 * 30
_SESSIONS: dict[str, tuple[int, float]] = {}


def initialize(connection: sqlite3.Connection) -> None:
    connection.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE COLLATE NOCASE,
            display_name TEXT NOT NULL,
            password_salt TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
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
    email, password = _require_credentials(email, password)
    name = (display_name or email.split("@", 1)[0]).strip() or "User"
    salt = secrets.token_bytes(16)
    password_hash = _hash_password(password, salt)
    try:
        cursor = connection.execute(
            "INSERT INTO users(email, display_name, password_salt, password_hash) VALUES(?,?,?,?)",
            (email, name[:80], salt.hex(), password_hash),
        )
        connection.commit()
    except sqlite3.IntegrityError as exc:
        raise ValueError("An account with that email already exists.") from exc
    return {"id": cursor.lastrowid, "email": email, "display_name": name[:80]}


def login(connection: sqlite3.Connection, email: str, password: str) -> tuple[str, dict[str, object]]:
    email, password = _require_credentials(email, password)
    row = connection.execute(
        "SELECT id, email, display_name, password_salt, password_hash FROM users WHERE email = ?",
        (email,),
    ).fetchone()
    if row is None or not hmac.compare_digest(_hash_password(password, bytes.fromhex(row[3])), row[4]):
        raise ValueError("Email or password is incorrect.")
    token = secrets.token_urlsafe(32)
    _SESSIONS[token] = (int(row[0]), _now() + _SESSION_TTL_SECONDS)
    return token, {"id": row[0], "email": row[1], "display_name": row[2]}


def logout(token: str | None) -> None:
    if token:
        _SESSIONS.pop(token, None)


def current_user(connection: sqlite3.Connection, token: str | None) -> dict[str, object] | None:
    if not token:
        return None
    session = _SESSIONS.get(token)
    if session is None:
        return None
    user_id, expiry = session
    if expiry <= _now():
        _SESSIONS.pop(token, None)
        return None
    row = connection.execute("SELECT id, email, display_name, created_at FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        _SESSIONS.pop(token, None)
        return None
    return {"id": row[0], "email": row[1], "display_name": row[2], "created_at": row[3]}


__all__ = ["initialize", "signup", "login", "logout", "current_user"]
