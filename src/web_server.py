"""WSGI composition for the full Personal AI System web shell.

The network endpoint remains owned by ``scripts/serve_web.py``. This module
only composes API adapters and serves static assets, while adding response
security headers and a lightweight same-origin check for cookie-authenticated
state-changing requests.
"""
from __future__ import annotations

from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import urlsplit

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

    def __call__(self, environ, start_response):
        path = environ.get("PATH_INFO", "/")
        method = str(environ.get("REQUEST_METHOD", "GET")).upper()
        if method in {"POST", "PUT", "PATCH", "DELETE"} and str(path).startswith("/api/") and not self._origin_allowed(environ):
            payload = b'{"error":"Request origin is not allowed for this session."}'
            start = self._start_response(environ, start_response)
            start("403 Forbidden", [("Content-Type", "application/json; charset=utf-8"), ("Content-Length", str(len(payload)))])
            return [payload]

        start = self._start_response(environ, start_response)
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


def create_site_app(api: WebApplication, web_root: str | Path | None = None, engineering_api: EngineeringWebApplication | None = None, integration_api: IntegrationWebApplication | None = None, calculation_navigation_api=None, calculation_execution_api=None, chat_actions=None, search_api=None) -> SiteApplication:
    return SiteApplication(api, web_root, engineering_api, integration_api, calculation_navigation_api, calculation_execution_api, chat_actions, search_api)


__all__ = ["SiteApplication", "create_site_app"]
