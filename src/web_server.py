"""WSGI composition for workspace, engineering, integration APIs, and static web shell."""
from __future__ import annotations

from pathlib import Path

from calculation_navigation_api import create_calculation_navigation_app
from chat_actions_web_api import create_chat_actions_app
from engineering_web_api import EngineeringWebApplication, create_engineering_app
from integration_web_api import IntegrationWebApplication, create_integration_app
from search_web_api import SearchWebApplication
from web_api import WebApplication


class SiteApplication:
    """Serve the web client and delegate each API namespace to its boundary."""

    def __init__(self, api: WebApplication, web_root: str | Path | None = None, engineering_api: EngineeringWebApplication | None = None, integration_api: IntegrationWebApplication | None = None, calculation_navigation_api=None, chat_actions=None, search_api=None):
        self.api = api
        self.engineering_api = engineering_api or create_engineering_app()
        self.integration_api = integration_api or create_integration_app()
        self.calculation_navigation_api = calculation_navigation_api or create_calculation_navigation_app()
        self.chat_actions = chat_actions or create_chat_actions_app()
        self.search_api = search_api or SearchWebApplication()
        self.web_root = Path(web_root or Path(__file__).resolve().parent.parent / "web")

    def __call__(self, environ, start_response):
        path = environ.get("PATH_INFO", "/")
        if path.startswith("/api/engineering/"):
            return self.engineering_api(environ, start_response)
        if path.startswith("/api/digest") or path.startswith("/api/connections") or path.startswith("/api/plugins"):
            return self.integration_api(environ, start_response)
        if path.startswith("/api/calculations/majors"):
            return self.calculation_navigation_api(environ, start_response)
        if path.rstrip("/") == "/api/search":
            return self.search_api(environ, start_response)
        if path.startswith("/api/chats/") and any(path.endswith(f"/{action}") for action in ("branch", "feedback")):
            return self.chat_actions(environ, start_response)
        if path.startswith("/api/"):
            return self.api(environ, start_response)
        relative = "index.html" if path in {"", "/"} else path.lstrip("/")
        root = self.web_root.resolve()
        candidate = (self.web_root / relative).resolve()
        if root not in candidate.parents and candidate != root:
            start_response("404 Error", [("Content-Type", "text/plain; charset=utf-8")])
            return [b"Not found"]
        if not candidate.is_file():
            start_response("404 Error", [("Content-Type", "text/plain; charset=utf-8")])
            return [b"Not found"]
        content_types = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".json": "application/json; charset=utf-8"}
        payload = candidate.read_bytes()
        start_response("200 OK", [("Content-Type", content_types.get(candidate.suffix, "application/octet-stream")), ("Content-Length", str(len(payload)))])
        return [payload]


def create_site_app(api: WebApplication, web_root: str | Path | None = None, engineering_api: EngineeringWebApplication | None = None, integration_api: IntegrationWebApplication | None = None, calculation_navigation_api=None, chat_actions=None, search_api=None) -> SiteApplication:
    return SiteApplication(api, web_root, engineering_api, integration_api, calculation_navigation_api, chat_actions, search_api)


__all__ = ["SiteApplication", "create_site_app"]
