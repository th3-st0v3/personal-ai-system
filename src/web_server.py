"""WSGI composition for the full Personal AI System web shell.

The network endpoint remains owned by ``scripts/serve_web.py``. This module
composes the API adapters, serves static assets, applies response security
headers, and enforces account-to-project/chat authorization at the HTTP edge.
"""
from __future__ import annotations

import io
import json
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import access_control
import auth_service
import db
from calculation_execution_web_api import create_calculation_execution_app
from calculation_navigation_api import create_calculation_navigation_app
from chat_actions_web_api import create_chat_actions_app
from engineering_web_api import EngineeringWebApplication, create_engineering_app
from integration_web_api import IntegrationWebApplication, create_integration_app
from search_web_api import SearchWebApplication
from web_api import WebApplication


class SiteApplication:
    """Serve the web client and delegate each API namespace to its boundary."""

    def __init__(self, api: WebApplication, web_root: str | Path | None = None, engineering_api: EngineeringWebApplication | None = None, integration_api: IntegrationWebApplication | None = None, calculation_navigation_api=None, calculation_execution_api=None, chat_actions=None, search_api=None):
        self.api = api
        self.engineering_api = engineering_api or create_engineering_app()
        self.integration_api = integration_api or create_integration_app()
        self.calculation_navigation_api = calculation_navigation_api or create_calculation_navigation_app()
        self.calculation_execution_api = calculation_execution_api or create_calculation_execution_app()
        self.chat_actions = chat_actions or create_chat_actions_app()
        self.search_api = search_api or SearchWebApplication()
        self.web_root = Path(web_root or Path(__file__).resolve().parent.parent / "web")
        connection = db.get_connection()
        try:
            auth_service.initialize(connection)
            from chat_service import initialize as initialize_chat
            initialize_chat(connection)
            access_control.initialize(connection)
        finally:
            connection.close()

    @staticmethod
    def _origin_allowed(environ: dict[str, object]) -> bool:
        origin = environ.get("HTTP_ORIGIN")
        if not origin:
            return True
        host = str(environ.get("HTTP_HOST", ""))
        if not host:
            return True
        forwarded_proto = str(environ.get("HTTP_X_FORWARDED_PROTO", "")).split(",", 1)[0].strip()
        proto = forwarded_proto or ("https" if environ.get("HTTPS") in {"on", "1"} else "http")
        parsed = urlsplit(str(origin))
        return bool(parsed.scheme and parsed.netloc) and parsed.scheme.casefold() == proto and parsed.netloc.casefold() == host.casefold()

    @staticmethod
    def _secure_cookie(environ: dict[str, object], value: str) -> str:
        cookie = SimpleCookie()
        try:
            cookie.load(value)
        except Exception:
            return value
        if "pas_session" not in cookie:
            return value
        morsel = cookie["pas_session"]
        forwarded_proto = str(environ.get("HTTP_X_FORWARDED_PROTO", "")).split(",", 1)[0].strip()
        is_secure = forwarded_proto.casefold() == "https" or environ.get("HTTPS") in {"on", "1"}
        if is_secure:
            morsel["secure"] = True
        morsel["httponly"] = True
        morsel["path"] = "/"
        if not morsel.get("samesite"):
            morsel["samesite"] = "Lax"
        return morsel.OutputString()

    @classmethod
    def _start_response(cls, environ: dict[str, object], start_response):
        def wrapped(status, headers, exc_info=None):
            transformed: list[tuple[str, str]] = []
            for name, value in ((str(n), str(v)) for n, v in headers):
                if name.casefold() == "set-cookie":
                    value = cls._secure_cookie(environ, value)
                transformed.append((name, value))
            existing = {name.casefold() for name, _ in transformed}
            security_headers = [
                ("X-Content-Type-Options", "nosniff"),
                ("X-Frame-Options", "DENY"),
                ("Referrer-Policy", "same-origin"),
                ("Permissions-Policy", "camera=(), microphone=(), geolocation=()"),
            ]
            if str(environ.get("PATH_INFO", "")).startswith("/api/"):
                security_headers.append(("Cache-Control", "no-store"))
            for name, value in security_headers:
                if name.casefold() not in existing:
                    transformed.append((name, value))
            if exc_info is None:
                return start_response(status, transformed)
            return start_response(status, transformed, exc_info)
        return wrapped

    @staticmethod
    def _session_user(environ: dict[str, object]) -> dict[str, object] | None:
        token = WebApplication._session_token(environ)
        connection = db.get_connection()
        try:
            return auth_service.current_user(connection, token)
        finally:
            connection.close()

    @staticmethod
    def _read_json_body(environ: dict[str, object]) -> dict[str, object]:
        length_raw = environ.get("CONTENT_LENGTH") or "0"
        try:
            length = int(str(length_raw))
        except (TypeError, ValueError) as exc:
            raise ValueError("Invalid content length.") from exc
        if length < 0 or length > WebApplication.MAX_REQUEST_BODY_BYTES:
            raise PermissionError("Request body too large.")
        if length == 0:
            environ["wsgi.input"] = io.BytesIO(b"")
            return {}
        stream = environ.get("wsgi.input")
        if not hasattr(stream, "read"):
            raise ValueError("Request body stream is unavailable.")
        body = stream.read(length)  # type: ignore[union-attr]
        if not isinstance(body, bytes):
            body = bytes(body)
        environ["wsgi.input"] = io.BytesIO(body)
        environ["CONTENT_LENGTH"] = str(len(body))
        try:
            parsed = json.loads(body or b"{}")
        except json.JSONDecodeError as exc:
            raise ValueError("Invalid JSON request body.") from exc
        if not isinstance(parsed, dict):
            raise ValueError("JSON request body must be an object.")
        return {str(key): value for key, value in parsed.items()}

    def _authorize(self, environ: dict[str, object], method: str, path: str, query: dict[str, str]) -> str | None:
        protected = path == "/api/projects" or path.startswith("/api/projects/") or path == "/api/chats" or path.startswith("/api/chats/") or path.startswith("/api/engineering/projects/")
        if not protected:
            return None
        user = self._session_user(environ)
        actor_id = None if user is None else str(user["id"])
        body: dict[str, object] = {}
        if method in {"POST", "PUT", "PATCH"}:
            body = self._read_json_body(environ)
        connection = db.get_connection()
        try:
            if path == "/api/projects":
                access_control.require_authenticated(connection, actor_id)
                return actor_id
            if path == "/api/chats":
                access_control.require_authenticated(connection, actor_id)
                project_id = body.get("project_id") if method == "POST" else query.get("project_id")
                if project_id is not None:
                    access_control.require_project(connection, actor_id, int(str(project_id)))
                return actor_id
            parts = [part for part in path.split("/") if part]
            if len(parts) >= 3 and parts[1] == "projects":
                project_id = int(parts[2])
                access_control.require_project(connection, actor_id, project_id)
                return actor_id
            if len(parts) >= 4 and parts[1:3] == ["engineering", "projects"]:
                project_id = int(parts[3])
                access_control.require_project(connection, actor_id, project_id)
                return actor_id
            if len(parts) >= 3 and parts[1] == "chats":
                chat_id = int(parts[2])
                access_control.require_chat(connection, actor_id, chat_id)
                target_project = body.get("project_id") if method == "PATCH" else None
                if target_project is not None:
                    access_control.require_project(connection, actor_id, int(str(target_project)))
                return actor_id
        finally:
            connection.close()
        return actor_id

    def _dispatch(self, environ, start):
        path = environ.get("PATH_INFO", "/")
        if path.startswith("/api/engineering/"):
            return self.engineering_api(environ, start)
        if path.startswith("/api/digest") or path.startswith("/api/connections") or path.startswith("/api/plugins"):
            return self.integration_api(environ, start)
        if path.rstrip("/") in {"/api/calculations/run", "/api/calculations/run/save"}:
            return self.calculation_execution_api(environ, start)
        if path.startswith("/api/calculations/majors"):
            return self.calculation_navigation_api(environ, start)
        if path.rstrip("/") == "/api/search":
            return self.search_api(environ, start)
        if path.startswith("/api/chats/") and any(path.endswith(f"/{action}") for action in ("branch", "feedback")):
            return self.chat_actions(environ, start)
        if path.startswith("/api/"):
            return self.api(environ, start)
        relative = "index.html" if path in {"", "/"} else path.lstrip("/")
        root = self.web_root.resolve()
        candidate = (self.web_root / relative).resolve()
        if root not in candidate.parents and candidate != root:
            start("404 Error", [("Content-Type", "text/plain; charset=utf-8")])
            return [b"Not found"]
        if not candidate.is_file():
            start("404 Error", [("Content-Type", "text/plain; charset=utf-8")])
            return [b"Not found"]
        content_types = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".json": "application/json; charset=utf-8"}
        payload = candidate.read_bytes()
        start("200 OK", [("Content-Type", content_types.get(candidate.suffix, "application/octet-stream")), ("Content-Length", str(len(payload)))])
        return [payload]

    def _capture_dispatch(self, environ) -> tuple[str, list[tuple[str, str]], bytes]:
        captured: dict[str, Any] = {}

        def capture_start(status, headers, exc_info=None):
            captured["status"] = status
            captured["headers"] = list(headers)
            if exc_info is not None:
                captured["exc_info"] = exc_info

        iterable = self._dispatch(environ, capture_start)
        try:
            body = b"".join(iterable)
        finally:
            close = getattr(iterable, "close", None)
            if callable(close):
                close()
        status = str(captured.get("status", "500 Error"))
        raw_headers = captured.get("headers", [])
        headers: list[tuple[str, str]] = []
        if isinstance(raw_headers, list):
            headers = [(str(pair[0]), str(pair[1])) for pair in raw_headers if isinstance(pair, (list, tuple)) and len(pair) >= 2]
        return status, headers, body

    def _filter_list_response(self, path: str, body: bytes, actor_id: str | None) -> bytes:
        if path not in {"/api/projects", "/api/chats"}:
            return body
        try:
            payload = json.loads(body)
        except (TypeError, json.JSONDecodeError):
            return body
        if not isinstance(payload, list):
            return body
        connection = db.get_connection()
        try:
            allowed = access_control.owned_project_ids(connection, actor_id) if path == "/api/projects" else access_control.owned_chat_ids(connection, actor_id)
        finally:
            connection.close()
        if allowed is None:
            return body
        filtered = []
        for row in payload:
            if not isinstance(row, dict):
                continue
            raw_id = row.get("id")
            try:
                row_id = int(raw_id) if isinstance(raw_id, (int, str, float)) and not isinstance(raw_id, bool) else None
            except (TypeError, ValueError):
                row_id = None
            if row_id is not None and row_id in allowed:
                filtered.append(row)
        return json.dumps(filtered, ensure_ascii=False, separators=(",", ":")).encode()

    def __call__(self, environ, start_response):
        path = str(environ.get("PATH_INFO", "/"))
        method = str(environ.get("REQUEST_METHOD", "GET")).upper()
        if method in {"POST", "PUT", "PATCH", "DELETE"} and path.startswith("/api/") and not self._origin_allowed(environ):
            payload = b'{"error":"Request origin is not allowed for this session."}'
            start = self._start_response(environ, start_response)
            start("403 Forbidden", [("Content-Type", "application/json; charset=utf-8"), ("Content-Length", str(len(payload)))])
            return [payload]
        try:
            normalized_path = path.rstrip("/") or "/"
            query = {key: values[-1] for key, values in parse_qs(str(environ.get("QUERY_STRING", ""))).items()}
            actor_id = self._authorize(environ, method, normalized_path, query)
            captured_paths = {"/api/projects", "/api/chats", "/api/auth/signup"}
            if normalized_path in captured_paths:
                status, headers, body = self._capture_dispatch(environ)
                if normalized_path == "/api/auth/signup" and status.startswith("201"):
                    try:
                        payload = json.loads(body)
                        user_id = int(str(payload["user"]["id"]))
                    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                        user_id = None
                    if user_id is not None:
                        connection = db.get_connection()
                        try:
                            access_control.claim_legacy_data(connection, user_id)
                        finally:
                            connection.close()
                elif normalized_path == "/api/projects" and method == "POST" and status.startswith("201") and actor_id is not None:
                    payload = json.loads(body)
                    connection = db.get_connection()
                    try:
                        access_control.claim_project(connection, int(str(payload["id"])), int(actor_id))
                    finally:
                        connection.close()
                elif normalized_path == "/api/chats" and method == "POST" and status.startswith("201") and actor_id is not None:
                    payload = json.loads(body)
                    connection = db.get_connection()
                    try:
                        access_control.claim_chat(connection, int(str(payload["id"])), int(actor_id))
                    finally:
                        connection.close()
                if method == "GET" and normalized_path in {"/api/projects", "/api/chats"} and status.startswith("200"):
                    body = self._filter_list_response(normalized_path, body, actor_id)
                    headers = [(name, value) for name, value in headers if name.casefold() != "content-length"]
                    headers.append(("Content-Length", str(len(body))))
                start = self._start_response(environ, start_response)
                start(status, headers)
                return [body]
            start = self._start_response(environ, start_response)
            return self._dispatch(environ, start)
        except PermissionError as exc:
            message = str(exc)
            status = "401 Unauthorized" if message == "Authentication required." else "403 Forbidden"
            payload = json.dumps({"error": message or "Permission denied"}, separators=(",", ":")).encode()
            start = self._start_response(environ, start_response)
            start(status, [("Content-Type", "application/json; charset=utf-8"), ("Content-Length", str(len(payload)))])
            return [payload]
        except (TypeError, ValueError, json.JSONDecodeError):
            payload = b'{"error":"Invalid request."}'
            start = self._start_response(environ, start_response)
            start("400 Bad Request", [("Content-Type", "application/json; charset=utf-8"), ("Content-Length", str(len(payload)))])
            return [payload]


def create_site_app(api: WebApplication, web_root: str | Path | None = None, engineering_api: EngineeringWebApplication | None = None, integration_api: IntegrationWebApplication | None = None, calculation_navigation_api=None, calculation_execution_api=None, chat_actions=None, search_api=None) -> SiteApplication:
    return SiteApplication(api, web_root, engineering_api, integration_api, calculation_navigation_api, calculation_execution_api, chat_actions, search_api)


__all__ = ["SiteApplication", "create_site_app"]
