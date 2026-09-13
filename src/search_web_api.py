"""Aggregate search boundary for chats, projects, notes, and calculations."""
from __future__ import annotations

import json
from http.cookies import SimpleCookie
from urllib.parse import parse_qs, urlsplit

import access_control
import auth_service
import chat_service
import db
import workspace_browser
from calculation_application import CalculationApplication


class SearchWebApplication:
    def __init__(self) -> None:
        # Search includes workspace notes, whose small browser schema is owned by
        # workspace_browser. Initialize it here so a fresh database can always
        # execute the aggregate search path without a hidden dependency on a
        # prior note operation.
        connection = workspace_browser._connection()
        connection.close()

    def _json(self, status: int, body: object) -> tuple[int, list[tuple[str, str]], bytes]:
        payload = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
        return status, [("Content-Type", "application/json; charset=utf-8"), ("Content-Length", str(len(payload)))], payload

    @staticmethod
    def _session_token(environ: dict[str, object]) -> str | None:
        raw = environ.get("HTTP_COOKIE")
        if not raw:
            return None
        cookie = SimpleCookie()
        try:
            cookie.load(str(raw))
        except Exception:
            return None
        return cookie["pas_session"].value if "pas_session" in cookie else None

    def _actor_id(self, environ: dict[str, object], connection) -> str | None:
        user = auth_service.current_user(connection, self._session_token(environ))
        return None if user is None else str(user["id"])

    def request(self, method: str, target: str, actor_id: str | None = None) -> tuple[int, list[tuple[str, str]], bytes]:
        try:
            parsed = urlsplit(target)
            if method != "GET" or parsed.path.rstrip("/") != "/api/search":
                return self._json(404, {"error": "Not found"})
            query = parse_qs(parsed.query).get("q", [""])[-1].strip().casefold()
            connection = db.get_connection()
            try:
                actor = access_control.require_authenticated(connection, actor_id)
                if not query:
                    return self._json(200, {"chats": [], "projects": [], "notes": [], "calculations": []})
                allowed_projects = access_control.owned_project_ids(connection, actor)
                allowed_chats = access_control.owned_chat_ids(connection, actor)
                chat_rows = chat_service.list_chats(connection)
                chats = [item for item in chat_rows if query in str(item["title"]).casefold() and (allowed_chats is None or int(item["id"]) in allowed_chats)]
                notes_rows = connection.execute(
                    "SELECT id,project_id,title,content FROM workspace_notes WHERE lower(title) LIKE ? OR lower(content) LIKE ? ORDER BY updated_at DESC LIMIT 30",
                    (f"%{query}%", f"%{query}%"),
                ).fetchall()
                notes = [
                    {"id": int(row[0]), "project_id": int(row[1]), "title": str(row[2]), "content": str(row[3])}
                    for row in notes_rows
                    if allowed_projects is None or int(row[1]) in allowed_projects
                ]
                project_rows = connection.execute(
                    "SELECT id,name,description FROM projects WHERE lower(name) LIKE ? OR lower(description) LIKE ? ORDER BY created_at DESC LIMIT 30",
                    (f"%{query}%", f"%{query}%"),
                ).fetchall()
                projects = [
                    {"id": int(row[0]), "name": str(row[1]), "description": str(row[2] or "")}
                    for row in project_rows
                    if allowed_projects is None or int(row[0]) in allowed_projects
                ]
            finally:
                connection.close()
            catalog = CalculationApplication().list_catalog_items()
            calculations = [
                {"key": item.key, "name": item.name, "domain": item.domain}
                for item in catalog
                if query in f"{item.key} {item.name} {item.domain}".casefold()
            ]
            return self._json(200, {"chats": chats[:30], "projects": projects[:30], "notes": notes[:30], "calculations": calculations[:30]})
        except PermissionError as exc:
            message = str(exc)
            return self._json(401 if message == "Authentication required." else 403, {"error": message or "Permission denied"})
        except (KeyError, ValueError, TypeError, json.JSONDecodeError):
            return self._json(400, {"error": "Invalid search request."})
        except Exception:
            return self._json(500, {"error": "Search failed"})

    def __call__(self, environ, start_response):
        target = environ.get("PATH_INFO", "/")
        if environ.get("QUERY_STRING"):
            target += "?" + environ["QUERY_STRING"]
        connection = db.get_connection()
        try:
            actor_id = self._actor_id(environ, connection)
        finally:
            connection.close()
        status, headers, payload = self.request(environ.get("REQUEST_METHOD", "GET"), target, actor_id)
        start_response(f"{status} {'OK' if status < 300 else 'Error'}", headers)
        return [payload]


__all__ = ["SearchWebApplication"]
