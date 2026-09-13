"""Small HTTP boundary for chat actions that are not message generation."""
from __future__ import annotations

import json
import sqlite3
from urllib.parse import urlsplit

import db


class ChatActionsWebApplication:
    def _json(self, status: int, body: object) -> tuple[int, list[tuple[str, str]], bytes]:
        payload = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
        return status, [("Content-Type", "application/json; charset=utf-8"), ("Content-Length", str(len(payload)))], payload

    @staticmethod
    def _chat_exists(connection: sqlite3.Connection, chat_id: int) -> tuple[int, int | None, str]:
        row = connection.execute("SELECT id, project_id, title FROM chats WHERE id=?", (chat_id,)).fetchone()
        if row is None: raise ValueError("Chat not found.")
        return int(row[0]), None if row[1] is None else int(row[1]), str(row[2])

    @staticmethod
    def _branch(connection: sqlite3.Connection, chat_id: int, title: str) -> int:
        _, project_id, _ = ChatActionsWebApplication._chat_exists(connection, chat_id)
        cursor = connection.execute("INSERT INTO chats(project_id,title) VALUES(?,?)", (project_id, " ".join(title.split())[:120] or "Branch"))
        new_id = cursor.lastrowid
        if new_id is None: raise RuntimeError("Database did not return a branch chat ID.")
        rows = connection.execute("SELECT role,content FROM chat_messages WHERE chat_id=? ORDER BY id", (chat_id,)).fetchall()
        for role, content in rows: connection.execute("INSERT INTO chat_messages(chat_id,role,content) VALUES(?,?,?)", (int(new_id), str(role), str(content)))
        connection.commit()
        return int(new_id)

    @staticmethod
    def _feedback(connection: sqlite3.Connection, chat_id: int, message_id: int, rating: str) -> dict[str, object]:
        if rating not in {"up", "down"}: raise ValueError("Rating must be up or down.")
        ChatActionsWebApplication._chat_exists(connection, chat_id)
        row = connection.execute("SELECT id FROM chat_messages WHERE id=? AND chat_id=? AND role='assistant'", (message_id, chat_id)).fetchone()
        if row is None: raise ValueError("Assistant message not found in chat.")
        connection.executescript("CREATE TABLE IF NOT EXISTS chat_feedback (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL, message_id INTEGER NOT NULL, rating TEXT NOT NULL CHECK(rating IN ('up','down')), created_at TEXT NOT NULL DEFAULT (datetime('now')), UNIQUE(chat_id,message_id), FOREIGN KEY(chat_id) REFERENCES chats(id) ON DELETE CASCADE, FOREIGN KEY(message_id) REFERENCES chat_messages(id) ON DELETE CASCADE); CREATE INDEX IF NOT EXISTS idx_chat_feedback_chat ON chat_feedback(chat_id);")
        connection.execute("INSERT INTO chat_feedback(chat_id,message_id,rating) VALUES(?,?,?) ON CONFLICT(chat_id,message_id) DO UPDATE SET rating=excluded.rating,created_at=datetime('now')", (chat_id, message_id, rating))
        connection.commit()
        return {"message_id": message_id, "rating": rating}

    def request(self, method: str, target: str, body: bytes = b"") -> tuple[int, list[tuple[str, str]], bytes]:
        try:
            path = urlsplit(target).path.rstrip("/")
            data = json.loads(body or b"{}")
            if not isinstance(data, dict): raise ValueError("JSON request body must be an object.")
            parts = path.split("/")
            if len(parts) == 5 and parts[:3] == ["", "api", "chats"]:
                chat_id = int(parts[3]); action = parts[4]
                connection = db.get_connection()
                try:
                    if method == "POST" and action == "branch": return self._json(201, {"id": self._branch(connection, chat_id, str(data.get("title", "Branch")))})
                    if method == "POST" and action == "feedback":
                        message_id = data.get("message_id")
                        if not isinstance(message_id, int): raise ValueError("message_id must be an integer.")
                        return self._json(200, self._feedback(connection, chat_id, message_id, str(data.get("rating", ""))))
                finally:
                    connection.close()
            return self._json(404, {"error": "Not found"})
        except (KeyError, ValueError, TypeError, json.JSONDecodeError) as exc:
            return self._json(400, {"error": str(exc) or "Invalid request"})
        except Exception as exc:
            return self._json(500, {"error": str(exc) or "Internal server error"})

    def __call__(self, environ, start_response):
        length = int(environ.get("CONTENT_LENGTH") or 0)
        body = environ["wsgi.input"].read(length) if length else b""
        target = environ.get("PATH_INFO", "/")
        if environ.get("QUERY_STRING"): target += "?" + environ["QUERY_STRING"]
        status, headers, payload = self.request(environ.get("REQUEST_METHOD", "GET"), target, body)
        start_response(f"{status} {'OK' if status < 300 else 'Error'}", headers)
        return [payload]


def create_chat_actions_app() -> ChatActionsWebApplication:
    return ChatActionsWebApplication()
