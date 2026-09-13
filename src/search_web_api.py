"""Aggregate search boundary for chats, projects, notes, and calculations."""
from __future__ import annotations

import json
from urllib.parse import parse_qs, urlsplit

import chat_service
import db
from calculation_application import CalculationApplication


class SearchWebApplication:
    def _json(self, status: int, body: object) -> tuple[int, list[tuple[str, str]], bytes]:
        payload = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
        return status, [("Content-Type", "application/json; charset=utf-8"), ("Content-Length", str(len(payload)))], payload

    def request(self, method: str, target: str) -> tuple[int, list[tuple[str, str]], bytes]:
        try:
            parsed = urlsplit(target)
            if method != "GET" or parsed.path.rstrip("/") != "/api/search":
                return self._json(404, {"error": "Not found"})
            query = parse_qs(parsed.query).get("q", [""])[-1].strip().casefold()
            if not query:
                return self._json(200, {"chats": [], "projects": [], "notes": [], "calculations": []})
            connection = db.get_connection()
            try:
                chats = [item for item in chat_service.list_chats(connection) if query in str(item["title"]).casefold()]
                notes = [
                    {"id": int(row[0]), "project_id": int(row[1]), "title": str(row[2]), "content": str(row[3])}
                    for row in connection.execute(
                        "SELECT id,project_id,title,content FROM workspace_notes WHERE lower(title) LIKE ? OR lower(content) LIKE ? ORDER BY updated_at DESC LIMIT 30",
                        (f"%{query}%", f"%{query}%"),
                    ).fetchall()
                ]
                projects = [
                    {"id": int(row[0]), "name": str(row[1]), "description": str(row[2] or "")}
                    for row in connection.execute(
                        "SELECT id,name,description FROM projects WHERE lower(name) LIKE ? OR lower(description) LIKE ? ORDER BY created_at DESC LIMIT 30",
                        (f"%{query}%", f"%{query}%"),
                    ).fetchall()
                ]
            finally:
                connection.close()
            catalog = CalculationApplication().list_catalog_items()
            calculations = [
                {"key": item.key, "name": item.name, "domain": item.domain}
                for item in catalog
                if query in f"{item.key} {item.name} {item.domain}".casefold()
            ]
            return self._json(200, {"chats": chats[:30], "projects": projects[:30], "notes": notes, "calculations": calculations[:30]})
        except Exception as exc:
            return self._json(500, {"error": str(exc) or "Search failed"})

    def __call__(self, environ, start_response):
        target = environ.get("PATH_INFO", "/")
        if environ.get("QUERY_STRING"):
            target += "?" + environ["QUERY_STRING"]
        status, headers, payload = self.request(environ.get("REQUEST_METHOD", "GET"), target)
        start_response(f"{status} {'OK' if status < 300 else 'Error'}", headers)
        return [payload]
