"""Persistent local account authentication for the beta web shell."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
from datetime import datetime, timezone

SESSION_TTL_SECONDS = 60 * 60 * 24 * 30
SESSION_TOKEN_BYTES = 32


def _columns(connection: sqlite3.Connection) -> set[str]:
    return {row[1] for row in connection.execute("PRAGMA table_info(users)").fetchall()}


def initialize(connection: sqlite3.Connection) -> None:
    """Create/migrate authentication tables.

    This function is intentionally an explicit schema hook. Call it from the
    application's startup/schema layer rather than from every auth operation.
    """
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL DEFAULT 'User',
            email TEXT NOT NULL UNIQUE COLLATE NOCASE,
            display_name TEXT NOT NULL DEFAULT 'User',
            password_salt TEXT NOT NULL DEFAULT '',
            password_hash TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'Active',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            expires_at REAL NOT NULL,
            last_seen_at REAL NOT NULL,
            rotated_from TEXT,
            revoked_at REAL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
        CREATE INDEX IF NOT EXISTS idx_sessions_expiry ON sessions(expires_at);
    """)
    columns = _columns(connection)
    migrations = {
        "name": "ALTER TABLE users ADD COLUMN name TEXT NOT NULL DEFAULT 'User'",
        "display_name": "ALTER TABLE users ADD COLUMN display_name TEXT NOT NULL DEFAULT 'User'",
        "password_salt": "ALTER TABLE users ADD COLUMN password_salt TEXT NOT NULL DEFAULT ''",
        "password_hash": "ALTER TABLE users ADD COLUMN password_hash TEXT NOT NULL DEFAULT ''",
        "status": "ALTER TABLE users ADD COLUMN status TEXT NOT NULL DEFAULT 'Active'",
        "email": "ALTER TABLE users ADD COLUMN email TEXT",
        "created_at": "ALTER TABLE users ADD COLUMN created_at TEXT NOT NULL DEFAULT ''",
    }
    for column, statement in migrations.items():
        if column not in columns:
            connection.execute(statement)
    connection.execute("UPDATE users SET name = COALESCE(NULLIF(name, ''), NULLIF(display_name, ''), 'User')")
    connection.execute("UPDATE users SET display_name = COALESCE(NULLIF(display_name, ''), NULLIF(name, ''), 'User')")
    connection.execute("DELETE FROM sessions WHERE revoked_at IS NOT NULL OR expires_at <= ?", (_now(),))
    connection.commit()


def _now() -> float:
    return datetime.now(timezone.utc).timestamp()


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _hash_password(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 180_000).hex()


def _require_credentials(email: str, password: str) -> tuple[str, str]:
    email = email.strip().casefold()
    if "@" not in email or len(email) < 5:
        raise ValueError("Enter a valid email address.")
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters.")
    return email, password


def _issue_session(connection: sqlite3.Connection, user_id: int, *, rotated_from: str | None = None) -> str:
    token = secrets.token_urlsafe(SESSION_TOKEN_BYTES)
    now = _now()
    connection.execute(
        "INSERT INTO sessions(token_hash,user_id,expires_at,last_seen_at,rotated_from) VALUES(?,?,?,?,?)",
        (_token_hash(token), user_id, now + SESSION_TTL_SECONDS, now, rotated_from),
    )
    connection.commit()
    return token


def signup(connection: sqlite3.Connection, email: str, password: str, display_name: str | None = None) -> dict[str, object]:
    email, password = _require_credentials(email, password)
    name = (display_name or email.split("@", 1)[0]).strip() or "User"
    salt = secrets.token_bytes(16)
    try:
        cursor = connection.execute(
            "INSERT INTO users(name,email,display_name,password_salt,password_hash,status) VALUES(?,?,?,?,?,?)",
            (name[:80], email, name[:80], salt.hex(), _hash_password(password, salt), "Active"),
        )
        connection.commit()
    except sqlite3.IntegrityError as exc:
        raise ValueError("An account with that email already exists.") from exc
    return {"id": cursor.lastrowid, "email": email, "display_name": name[:80]}


def login(connection: sqlite3.Connection, email: str, password: str) -> tuple[str, dict[str, object]]:
    email, password = _require_credentials(email, password)
    row = connection.execute(
        "SELECT id,email,name,display_name,password_salt,password_hash,status FROM users WHERE email=?",
        (email,),
    ).fetchone()
    if row is None:
        raise ValueError("Email or password is incorrect.")
    if str(row[6]).casefold() != "active":
        raise ValueError("This account is not active.")
    try:
        valid = hmac.compare_digest(_hash_password(password, bytes.fromhex(row[4])), row[5])
    except (TypeError, ValueError):
        valid = False
    if not valid:
        raise ValueError("Email or password is incorrect.")

    # One successful login invalidates older active sessions for the same user.
    now = _now()
    connection.execute(
        "UPDATE sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL AND expires_at>?",
        (now, int(row[0]), now),
    )
    token = _issue_session(connection, int(row[0]))
    return token, {"id": row[0], "email": row[1], "display_name": row[3] or row[2] or "User"}


def rotate_session(connection: sqlite3.Connection, token: str | None) -> str | None:
    """Rotate a live session token and revoke the old identifier."""
    if not token:
        return None
    token_hash = _token_hash(token)
    now = _now()
    row = connection.execute(
        "SELECT user_id,expires_at,revoked_at FROM sessions WHERE token_hash=?",
        (token_hash,),
    ).fetchone()
    if row is None or row[2] is not None or float(row[1]) <= now:
        return None
    connection.execute("UPDATE sessions SET revoked_at=?,last_seen_at=? WHERE token_hash=?", (now, now, token_hash))
    return _issue_session(connection, int(row[0]), rotated_from=token_hash)


def logout(connection: sqlite3.Connection, token: str | None) -> None:
    if not token:
        return
    connection.execute(
        "UPDATE sessions SET revoked_at=? WHERE token_hash=? AND revoked_at IS NULL",
        (_now(), _token_hash(token)),
    )
    connection.commit()


def current_user(connection: sqlite3.Connection, token: str | None) -> dict[str, object] | None:
    if not token:
        return None
    now = _now()
    token_hash = _token_hash(token)
    row = connection.execute(
        """
        SELECT s.user_id, s.expires_at, u.id, u.email, u.name, u.display_name, u.created_at, u.status
        FROM sessions s JOIN users u ON u.id=s.user_id
        WHERE s.token_hash=? AND s.revoked_at IS NULL
        """,
        (token_hash,),
    ).fetchone()
    if row is None:
        return None
    if float(row[1]) <= now or str(row[7]).casefold() != "active":
        connection.execute("UPDATE sessions SET revoked_at=? WHERE token_hash=?", (now, token_hash))
        connection.commit()
        return None
    connection.execute("UPDATE sessions SET last_seen_at=? WHERE token_hash=?", (now, token_hash))
    connection.commit()
    return {
        "id": row[2],
        "email": row[3],
        "display_name": row[5] or row[4] or "User",
        "created_at": row[6],
    }


def purge_expired_sessions(connection: sqlite3.Connection) -> int:
    cursor = connection.execute(
        "DELETE FROM sessions WHERE expires_at<=? OR revoked_at IS NOT NULL",
        (_now(),),
    )
    connection.commit()
    return cursor.rowcount


__all__ = [
    "SESSION_TTL_SECONDS",
    "initialize",
    "signup",
    "login",
    "rotate_session",
    "logout",
    "current_user",
    "purge_expired_sessions",
]
