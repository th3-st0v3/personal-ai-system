"""Small, replaceable HTTP boundary over the stable application services."""
from __future__ import annotations

import json
from urllib.parse import parse_qs, urlsplit

from calculation_application import CalculationApplication
from workspace_application import WorkspaceApplication


class WebApplication:
    """Serve JSON API resources without coupling HTTP handlers to storage."""

    def __init__(self, workspace: WorkspaceApplication, calculations: CalculationApplication | None = None):
        self.workspace = workspace
        self.calculations = calculations or CalculationApplication()

    @staticmethod
    def _json(status: int, body: object) -> tuple[int, list[tuple[str, str]], bytes]:
        payload = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
        return status, [("Content-Type", "application/json; charset=utf-8"), ("Content-Length", str(len(payload)))], payload

    @staticmethod
    def _item(item) -> dict[str, object]:
        return {"kind": item.kind, "id": item.id, "project_id": item.project_id, "parent_id": item.parent_id, "name": item.name, "mime_type": item.mime_type, "content": item.content, "size_bytes": item.size_bytes, "created_at": item.created_at, "updated_at": item.updated_at, "metadata": item.metadata}

    def request(self, method: str, target: str, body: bytes = b"") -> tuple[int, list[tuple[str, str]], bytes]:
        try:
            parsed = urlsplit(target)
            path = parsed.path.rstrip("/") or "/"
            query = {key: values[-1] for key, values in parse_qs(parsed.query).items()}
            data = json.loads(body or b"{}")
            if method == "GET" and path == "/api/health":
                return self._json(200, {"status": "ok"})
            if method == "GET" and path == "/api/projects":
                return self._json(200, self.workspace.list_projects())
            if method == "POST" and path == "/api/projects":
                return self._json(201, {"id": self.workspace.create_project(data["name"], data.get("description"))})
            if method == "GET" and path == "/api/calculations/categories":
                return self._json(200, self.calculations.grouped_categories())
            if method == "GET" and path == "/api/calculations/catalog":
                return self._json(200, [item.__dict__ for item in self.calculations.list_catalog_items(query.get("category"))])
            if method == "POST" and path == "/api/calculations/run":
                return self._json(200, self.calculations.run_trace(data["model_key"], data.get("inputs", {})).to_dict())
            parts = path.split("/")
            if len(parts) >= 4 and parts[1:3] == ["api", "projects"]:
                project_id = int(parts[3])
                if method == "GET" and len(parts) == 5 and parts[4] == "items":
                    folder_id = int(query["folder_id"]) if query.get("folder_id") else None
                    return self._json(200, [self._item(item) for item in self.workspace.list_children(project_id, folder_id, sort=query.get("sort", "a_z"))])
                if method == "GET" and len(parts) == 5 and parts[4] == "search":
                    return self._json(200, [self._item(item) for item in self.workspace.search_project(project_id, query["q"], recursive=query.get("recursive", "true").casefold() != "false")])
                if method == "POST" and len(parts) == 5 and parts[4] == "folders":
                    return self._json(201, {"id": self.workspace.create_folder(project_id, data["name"], data.get("parent_folder_id"))})
                if method == "POST" and len(parts) == 5 and parts[4] == "notes":
                    return self._json(201, {"id": self.workspace.create_note(project_id, data["title"], data.get("content", ""), data.get("folder_id"), data.get("metadata"))})
                if method == "POST" and len(parts) == 5 and parts[4] == "move":
                    kind, item_id = data["kind"], int(data["id"])
                    item = self.workspace._browser_item(kind, item_id)
                    if item.project_id != project_id:
                        raise ValueError("Item belongs to another project.")
                    self.workspace.move_item(kind, item_id, data.get("target_folder_id"))
                    return self._json(200, {"moved": True})
                if method == "POST" and len(parts) == 5 and parts[4] == "rename":
                    kind, item_id = data["kind"], int(data["id"])
                    item = self.workspace._browser_item(kind, item_id)
                    if item.project_id != project_id:
                        raise ValueError("Item belongs to another project.")
                    self.workspace.rename_item(kind, item_id, data["name"])
                    return self._json(200, {"renamed": True})
                if method == "POST" and len(parts) == 5 and parts[4] == "delete":
                    selection = [(item["kind"], int(item["id"])) for item in data.get("selection", [])]
                    if not selection:
                        selection = [(data["kind"], int(data["id"]))]
                    return self._json(200, {"deleted": self.workspace.delete_selection(project_id, selection)})
                if method == "GET" and len(parts) == 5 and parts[4] == "properties":
                    kind, item_id = query["kind"], int(query["id"])
                    properties = self.workspace.get_item_properties(kind, item_id)
                    if properties["project_id"] != project_id:
                        raise ValueError("Item belongs to another project.")
                    return self._json(200, properties)
            return self._json(404, {"error": "Not found"})
        except (KeyError, ValueError, TypeError, json.JSONDecodeError) as exc:
            return self._json(400, {"error": str(exc) or "Invalid request"})
        except Exception as exc:
            return self._json(500, {"error": str(exc) or "Internal server error"})

    def __call__(self, environ, start_response):
        length = int(environ.get("CONTENT_LENGTH") or 0)
        body = environ["wsgi.input"].read(length) if length else b""
        target = environ.get("PATH_INFO", "/")
        if environ.get("QUERY_STRING"):
            target += "?" + environ["QUERY_STRING"]
        status, headers, payload = self.request(environ.get("REQUEST_METHOD", "GET"), target, body)
        reason = "OK" if status < 300 else "Error"
        start_response(f"{status} {reason}", headers)
        return [payload]


def create_app(workspace: WorkspaceApplication, calculations: CalculationApplication | None = None) -> WebApplication:
    """Construct the replaceable WSGI application used by a future web server."""
    return WebApplication(workspace, calculations)


__all__ = ["WebApplication", "create_app"]
