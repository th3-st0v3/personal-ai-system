"""Persistent project-aware chat storage with optional tool-aware OpenRouter responses."""
from __future__ import annotations

import json
import os
import sqlite3
import urllib.request

import db
import engineering_modeler
import simulation_library
from calculation_application import CalculationApplication

_MAX_TOOL_ROUNDS = 4


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
    rows = connection.execute("SELECT id, project_id, title, created_at, updated_at FROM chats WHERE project_id IS ? ORDER BY updated_at DESC, id DESC", (project_id,)).fetchall()
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


def _tools() -> list[dict[str, object]]:
    return [
        {"type":"function","function":{"name":"run_calculation","description":"Run one deterministic engineering calculator and return its transparent trace.","parameters":{"type":"object","properties":{"model_key":{"type":"string"},"inputs":{"type":"object","additionalProperties":{"type":"number"}}},"required":["model_key","inputs"]}}},
        {"type":"function","function":{"name":"run_simulation","description":"Run one deterministic engineering simulation and return outputs, steps, assumptions, and limitations.","parameters":{"type":"object","properties":{"simulation_key":{"type":"string"},"inputs":{"type":"object","additionalProperties":{"type":"number"}}},"required":["simulation_key","inputs"]}}},
        {"type":"function","function":{"name":"get_project_items","description":"List the active project workspace items so you can reason over project material.","parameters":{"type":"object","properties":{}}}},
    ]


def _tool_result(connection: sqlite3.Connection, name: str, arguments: dict[str, object], project_id: int | None) -> dict[str, object]:
    if name == "run_calculation":
        return CalculationApplication().run_trace(str(arguments["model_key"]), arguments.get("inputs", {})).to_dict()
    if name == "run_simulation":
        return simulation_library.run_simulation(str(arguments["simulation_key"]), arguments.get("inputs", {}))
    if name == "get_project_items":
        if project_id is None:
            return {"items": [], "note": "This chat is outside a project."}
        rows = connection.execute("SELECT id, folder_id, title, content FROM workspace_notes WHERE project_id=? ORDER BY updated_at DESC", (project_id,)).fetchall()
        return {"items": [{"kind":"note","id":r[0],"folder_id":r[1],"name":r[2],"content":r[3]} for r in rows]}
    raise ValueError(f"Unsupported tool '{name}'.")


def _openrouter(messages: list[dict[str, object]], project_id: int | None, model: str | None = None) -> str | None:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        return None
    request_messages = [{"role":"system","content":"You are Personal AI System, an engineering-focused assistant. Prefer deterministic tools for calculations and simulations. Show assumptions and limitations. Do not claim a tool result that was not run."}] + messages
    for _ in range(_MAX_TOOL_ROUNDS):
        payload = json.dumps({"model": model or os.environ.get("OPENROUTER_MODEL", "openai/gpt-4o-mini"),"messages":request_messages,"tools":_tools(),"tool_choice":"auto"}).encode("utf-8")
        request = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions",data=payload,headers={"Authorization":f"Bearer {api_key}","Content-Type":"application/json","HTTP-Referer":"http://localhost"},method="POST")
        with urllib.request.urlopen(request, timeout=45) as response: data=json.loads(response.read().decode("utf-8"))
        message=data["choices"][0]["message"]; tool_calls=message.get("tool_calls") or []
        if not tool_calls: return message.get("content") or ""
        request_messages.append(message)
        for call in tool_calls:
            function=call["function"]; arguments=json.loads(function.get("arguments") or "{}")
            tool_connection=db.get_connection()
            try: result=_tool_result(tool_connection,function["name"],arguments,project_id)
            except Exception as exc: result={"error":str(exc)}
            finally: tool_connection.close()
            request_messages.append({"role":"tool","tool_call_id":call["id"],"content":json.dumps(result,ensure_ascii=False)})
    return "The model reached the tool-call limit before producing a final answer."


def _local_answer(content: str) -> str:
    tokens = content.casefold().split()
    if any(word in tokens for word in ("model", "simulate", "simulation", "calculate", "calculator")):
        plan=engineering_modeler.build_model_plan(content)
        lines=[f"Discipline: {plan['discipline']}",f"Objective: {plan['objective']}","Suggested calculations:"]
        lines += [f"- {item['name']} ({item['key']}): {item['equation']}" for item in plan["calculations"]] or ["- None matched yet."]
        if plan["simulations"]: lines += ["Suggested simulations:"]+[f"- {item['name']} ({item['key']})" for item in plan["simulations"]]
        lines += ["Assumptions:"]+[f"- {item}" for item in plan["assumptions"]]
        if plan["open_questions"]: lines += ["Open questions:"]+[f"- {item}" for item in plan["open_questions"]]
        lines.append(plan["next_step"])
        return "\n".join(lines)
    return "I’m in local mode. Connect an OpenRouter API key to enable a frontier-model response with calculation and simulation tools; deterministic engineering planning, calculations, simulations, and project data remain available without it."


def respond(connection: sqlite3.Connection, chat_id: int, content: str, *, model: str | None = None, mode: str = "auto") -> dict[str, object]:
    chat=get_chat(connection,chat_id); add_message(connection,chat_id,"user",content)
    messages=[{"role":message["role"],"content":message["content"]} for message in get_chat(connection,chat_id)["messages"]]
    answer=None if mode=="local" else _openrouter(messages,chat["project_id"],model=model)
    if answer is None: answer=_local_answer(content)
    add_message(connection,chat_id,"assistant",answer)
    if chat["title"]=="New chat":
        title=" ".join(content.strip().split())[:64] or "New chat"; connection.execute("UPDATE chats SET title=?, updated_at=datetime('now') WHERE id=?",(title,chat_id)); connection.commit()
    return get_chat(connection,chat_id)


__all__=["initialize","create_chat","list_chats","get_chat","add_message","respond"]
