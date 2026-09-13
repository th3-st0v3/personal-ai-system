"""Small HTTP boundary for chat actions that are not message generation."""
from __future__ import annotations

import json
from urllib.parse import urlsplit

import chat_service
import db


class ChatActionsWebApplication:
    def _json(self, status: int, body: object) -> tuple[int, list[tuple[str, str]], bytes]:
        payload = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
        return status, [("Content-Type", "application/json; charset=utf-8"), ("Content-Length", str(len(payload)))], payload

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
                    if method == "POST" and action == "branch": return self._json(201, {"id": chat_service.branch_chat(connection, chat_id, str(data.get("title", "Branch")))})
                    if method == "POST" and action == "feedback":
                        message_id = data.get("message_id")
                        if not isinstance(message_id, int): raise ValueError("message_id must be an integer.")
                        return self._json(200, chat_service.rate_message(connection, chat_id, message_id, str(data.get("rating", ""))))
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
