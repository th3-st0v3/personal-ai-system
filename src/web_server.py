"""WSGI composition for the API and static beta web shell."""
from __future__ import annotations

from pathlib import Path

from web_api import WebApplication


class SiteApplication:
    """Serve the web client and delegate API requests to WebApplication."""

    def __init__(self, api: WebApplication, web_root: str | Path | None = None):
        self.api = api
        self.web_root = Path(web_root or Path(__file__).resolve().parent.parent / "web")

    def __call__(self, environ, start_response):
        path = environ.get("PATH_INFO", "/")
        if path.startswith("/api/"):
            return self.api(environ, start_response)
        relative = "index.html" if path in {"", "/"} else path.lstrip("/")
        candidate = (self.web_root / relative).resolve()
        if self.web_root.resolve() not in candidate.parents and candidate != self.web_root.resolve():
            start_response("404 Error", [("Content-Type", "text/plain; charset=utf-8")])
            return [b"Not found"]
        if not candidate.is_file():
            start_response("404 Error", [("Content-Type", "text/plain; charset=utf-8")])
            return [b"Not found"]
        content_types = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".json": "application/json; charset=utf-8"}
        payload = candidate.read_bytes()
        start_response("200 OK", [("Content-Type", content_types.get(candidate.suffix, "application/octet-stream")), ("Content-Length", str(len(payload)))])
        return [payload]


def create_site_app(api: WebApplication, web_root: str | Path | None = None) -> SiteApplication:
    """Compose the API and static client without coupling either layer to a server."""
    return SiteApplication(api, web_root)


__all__ = ["SiteApplication", "create_site_app"]
