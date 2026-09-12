"""Persistent project-aware chat storage with an optional OpenRouter bridge."""
from __future__ import annotations

import json
import os
import sqlite3
import urllib.request



def initialize(connection: sqlite3.Connection) -> None:
    connection.executescript("""
    CREATE TABLE IF NOT EXISTS chats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER,
        title TEXT NOT NULL DEFAULT 'New chat',
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS chat_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('system','user','assistant','tool')),
        content TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY(chat_id) REFERENCES chats(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_chats_project_updated ON chats(project_id, updated_at DESC);
    CREATE INDEX IF NOT EXISTS idx_chat_messages_chat ON chat_messages(chat_id, id);
    """)
    connection.commit()


def create_chat(connection: sqlite3.Connection, project_id: int | None = None, title: str = "New chat") -> int:
    if project_id is not None and connection.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone() is None:
        raise ValueError("Project not found.")
    cursor = connection.execute("INSERT INTO chats(project_id,title) VALUES(?,?)", (project_id, title.strip() or "New chat"))
    connection.commit()
    return int(cursor.lastrowid)


def list_chats(connection: sqlite3.Connection, project_id: int | None = None) -> list[dict[str, object]]:
    rows = connection.execute(
        "SELECT id, project_id, title, created_at, updated_at FROM chats WHERE project_id IS ? ORDER BY updated_at DESC, id DESC",
        (project_id,),
    ).fetchall()
    return [{"id": r[0], "project_id": r[1], "title": r[2], "created_at": r[3], "updated_at": r[4]} for r in rows]


def get_chat(connection: sqlite3.Connection, chat_id: int) -> dict[str, object]:
    row = connection.execute("SELECT id, project_id, title, created_at, updated_at FROM chats WHERE id=?", (chat_id,)).fetchone()
    if row is None:
        raise ValueError("Chat not found.")
    messages = connection.execute("SELECT id, role, content, created_at FROM chat_messages WHERE chat_id=? ORDER BY id", (chat_id,)).fetchall()
    return {"id": row[0], "project_id": row[1], "title": row[2], "created_at": row[3], "updated_at": row[4], "messages": [{"id": m[0], "role": m[1], "content": m[2], "created_at": m[3]} for m in messages]}


def add_message(connection: sqlite3.Connection, chat_id: int, role: str, content: str) -> int:
    if role not in {"system", "user", "assistant", "tool"}:
        raise ValueError("Unsupported message role.")
    if connection.execute("SELECT 1 FROM chats WHERE id=?", (chat_id,)).fetchone() is None:
        raise ValueError("Chat not found.")
    cursor = connection.execute("INSERT INTO chat_messages(chat_id,role,content) VALUES(?,?,?)", (chat_id, role, content))
    connection.execute("UPDATE chats SET updated_at=datetime('now') WHERE id=?", (chat_id,))
    connection.commit()
    return int(cursor.lastrowid)


def _openrouter(messages: list[dict[str, str]], model: str | None = None) -> str | None:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        return None
    payload = json.dumps({"model": model or os.environ.get("OPENROUTER_MODEL", "openai/gpt-4o-mini"), "messages": messages}).encode("utf-8")
    request = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=payload,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "HTTP-Referer": "http://localhost"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            data = json.loads(response.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]
    except Exception:
        return None


def respond(connection: sqlite3.Connection, chat_id: int, content: str, *, model: str | None = None) -> dict[str, object]:
    chat = get_chat(connection, chat_id)
    add_message(connection, chat_id, "user", content)
    history = [{"role": message["role"], "content": message["content"]} for message in get_chat(connection, chat_id)["messages"]]
    answer = _openrouter(history, model=model)
    if answer is None:
        answer = "I’m in local mode. Connect an OpenRouter API key to enable a frontier-model response; project tools and deterministic engineering calculations remain available without it."
    add_message(connection, chat_id, "assistant", answer)
    if chat["title"] == "New chat":
        title = " ".join(content.strip().split())[:64] or "New chat"
        connection.execute("UPDATE chats SET title=?, updated_at=datetime('now') WHERE id=?", (title, chat_id))
        connection.commit()
    return get_chat(connection, chat_id)


__all__ = ["initialize", "create_chat", "list_chats", "get_chat", "add_message", "respond"]
