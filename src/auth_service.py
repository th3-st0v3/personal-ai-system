"""Persistent local account authentication for the beta web shell."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
from datetime import datetime, timezone
from typing import cast

SESSION_TTL_SECONDS = 60 * 60 * 24 * 30
SESSION_TOKEN_BYTES = 32
LOGIN_FAILURE_WINDOW_SECONDS = 15 * 60
LOGIN_MAX_FAILURES = 5
LOGIN_LOCKOUT_SECONDS = 15 * 60


def _columns(connection: sqlite3.Connection) -> set[str]:
    return {row[1] for row in connection.execute("PRAGMA table_info(users)").fetchall()}


def initialize(connection: sqlite3.Connection) -> None:
    """Create/migrate authentication tables; application startup owns schema initialization."""
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
        CREATE TABLE IF NOT EXISTS login_attempts (
            throttle_key TEXT PRIMARY KEY,
            failure_count INTEGER NOT NULL DEFAULT 0,
            first_failed_at REAL NOT NULL,
            last_failed_at REAL NOT NULL,
            locked_until REAL NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_login_attempts_lock ON login_attempts(locked_until);
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
    now = _now()
    connection.execute("DELETE FROM sessions WHERE revoked_at IS NOT NULL OR expires_at <= ?", (now,))
    connection.execute(
        "DELETE FROM login_attempts WHERE last_failed_at <= ? AND locked_until <= ?",
        (now - LOGIN_FAILURE_WINDOW_SECONDS, now),
    )
    connection.commit()


def _now() -> float:
    return datetime.now(timezone.utc).timestamp()


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _hash_password(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 180_000).hex()


def _require_credentials(email: str, password: str) -> tuple[str, str]:
    email = str(email).strip().casefold()
    password = str(password)
    if "@" not in email or len(email) < 5:
        raise ValueError("Enter a valid email address.")
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters.")
    return email, password


def _login_throttle_keys(email: str, client_ip: str | None) -> tuple[str, ...]:
    keys = [f"email:{email}"]
    normalized_ip = str(client_ip or "").strip()
    if normalized_ip:
        keys.append(f"ip:{normalized_ip}")
    return tuple(keys)


def _login_throttle_locked(
    connection: sqlite3.Connection,
    keys: tuple[str, ...],
    now: float,
) -> bool:
    for key in keys:
        row = connection.execute(
            "SELECT failure_count,first_failed_at,locked_until FROM login_attempts WHERE throttle_key=?",
            (key,),
        ).fetchone()
        if row is None:
            continue
        failure_count = int(row[0])
        first_failed_at = float(row[1])
        locked_until = float(row[2])
        if first_failed_at + LOGIN_FAILURE_WINDOW_SECONDS <= now:
            connection.execute(
                "DELETE FROM login_attempts WHERE throttle_key=?",
                (key,),
            )
            continue
        if locked_until > now or failure_count >= LOGIN_MAX_FAILURES:
            return True
    return False


def _record_login_failure(
    connection: sqlite3.Connection,
    keys: tuple[str, ...],
    now: float,
) -> None:
    for key in keys:
        row = connection.execute(
            "SELECT failure_count,first_failed_at FROM login_attempts WHERE throttle_key=?",
            (key,),
        ).fetchone()
        if row is None or float(row[1]) + LOGIN_FAILURE_WINDOW_SECONDS <= now:
            connection.execute(
                "INSERT OR REPLACE INTO login_attempts(throttle_key,failure_count,first_failed_at,last_failed_at,locked_until) VALUES(?,?,?,?,?)",
                (key, 1, now, now, 0),
            )
            continue
        failure_count = int(row[0]) + 1
        locked_until = (
            now + LOGIN_LOCKOUT_SECONDS
            if failure_count >= LOGIN_MAX_FAILURES
            else 0
        )
        connection.execute(
            "UPDATE login_attempts SET failure_count=?,last_failed_at=?,locked_until=? WHERE throttle_key=?",
            (failure_count, now, locked_until, key),
        )
    connection.commit()


def _clear_login_failures(connection: sqlite3.Connection, keys: tuple[str, ...]) -> None:
    for key in keys:
        connection.execute(
            "DELETE FROM login_attempts WHERE throttle_key=?",
            (key,),
        )
    connection.commit()


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


def login(
    connection: sqlite3.Connection,
    email: str,
    password: str,
    client_ip: str | None = None,
) -> tuple[str, dict[str, object]]:
    email, password = _require_credentials(email, password)
    throttle_keys = _login_throttle_keys(email, client_ip)
    now = _now()
    if _login_throttle_locked(connection, throttle_keys, now):
        connection.commit()
        raise ValueError("Email or password is incorrect.")
    row = connection.execute(
        "SELECT id,email,name,display_name,password_salt,password_hash,status FROM users WHERE email=?",
        (email,),
    ).fetchone()
    if row is None:
        _record_login_failure(connection, throttle_keys, now)
        raise ValueError("Email or password is incorrect.")
    if str(row[6]).casefold() != "active":
        raise ValueError("This account is not active.")
    try:
        valid = hmac.compare_digest(_hash_password(password, bytes.fromhex(row[4])), row[5])
    except (TypeError, ValueError):
        valid = False
    if not valid:
        _record_login_failure(connection, throttle_keys, now)
        raise ValueError("Email or password is incorrect.")
    _clear_login_failures(connection, throttle_keys)
    token = _issue_session(connection, int(row[0]))
    return token, {"id": row[0], "email": row[1], "display_name": row[3] or row[2] or "User"}


def rotate_session(connection: sqlite3.Connection, token: str | None) -> str | None:
    if not token:
        return None
    token_hash = _token_hash(token)
    now = _now()
    row = connection.execute("SELECT user_id,expires_at,revoked_at FROM sessions WHERE token_hash=?", (token_hash,)).fetchone()
    if row is None or row[2] is not None or float(row[1]) <= now:
        return None
    connection.execute("UPDATE sessions SET revoked_at=?,last_seen_at=? WHERE token_hash=?", (now, now, token_hash))
    return _issue_session(connection, int(row[0]), rotated_from=token_hash)


def logout(connection_or_token: sqlite3.Connection | str | None, token: str | None = None) -> None:
    """Revoke a session.

    The preferred form is ``logout(connection, token)``. The single-token form
    remains as a compatibility adapter for legacy web handlers and opens the
    configured database through ``db.get_connection``.
    """
    if token is None and not isinstance(connection_or_token, sqlite3.Connection):
        token_value = cast(str | None, connection_or_token)
        if not token_value:
            return
        import db
        connection = db.get_connection()
        try:
            logout(connection, token_value)
        finally:
            connection.close()
        return
    connection = cast(sqlite3.Connection, connection_or_token)
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
    return {"id": row[2], "email": row[3], "display_name": row[5] or row[4] or "User", "created_at": row[6]}


def purge_expired_sessions(connection: sqlite3.Connection) -> int:
    cursor = connection.execute("DELETE FROM sessions WHERE expires_at<=? OR revoked_at IS NOT NULL", (_now(),))
    connection.commit()
    return cursor.rowcount


__all__ = ["SESSION_TTL_SECONDS", "LOGIN_FAILURE_WINDOW_SECONDS", "LOGIN_MAX_FAILURES", "LOGIN_LOCKOUT_SECONDS", "initialize", "signup", "login", "rotate_session", "logout", "current_user", "purge_expired_sessions"]
