"""Project-scoped web boundary for engineering requirements and evidence."""
from __future__ import annotations

import json
from urllib.parse import parse_qs, urlsplit

import db
from engineering_application import EngineeringApplication


class EngineeringWebApplication:
    """Expose engineering evidence workflows without coupling them to the core workspace API."""

    def __init__(self, engineering: EngineeringApplication | None = None):
        self.engineering = engineering or EngineeringApplication()

    @staticmethod
    def _json(status: int, body: object) -> tuple[int, list[tuple[str, str]], bytes]:
        payload = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
        return status, [("Content-Type", "application/json; charset=utf-8"), ("Content-Length", str(len(payload)))], payload

    @staticmethod
    def _require_project(project_id: int) -> None:
        if db.get_project(project_id) is None:
            raise ValueError(f"No project found with ID {project_id}.")

    @staticmethod
    def _require_requirement(project_id: int, requirement_id: int) -> None:
        row = db.get_requirement(requirement_id)
        if row is None or row[1] != project_id:
            raise ValueError("Requirement not found in project.")

    def request(self, method: str, target: str, body: bytes = b"") -> tuple[int, list[tuple[str, str]], bytes]:
        try:
            parsed = urlsplit(target)
            path = parsed.path.rstrip("/") or "/"
            query = {key: values[-1] for key, values in parse_qs(parsed.query).items()}
            data = json.loads(body or b"{}")
            if not isinstance(data, dict):
                raise ValueError("JSON request body must be an object.")
            parts = path.strip("/").split("/")
            if len(parts) < 3 or parts[:3] != ["api", "engineering", "projects"]:
                return self._json(404, {"error": "Not found"})
            project_id = int(parts[3]) if len(parts) > 3 else None
            if project_id is None:
                return self._json(404, {"error": "Not found"})
            self._require_project(project_id)
            resource = parts[4] if len(parts) > 4 else ""
            if method == "GET" and resource == "requirements":
                return self._json(200, self.engineering.list_requirements(project_id))
            if method == "POST" and resource == "requirements":
                description = data["description"]
                return self._json(201, {"id": db.create_requirement(project_id, description)})
            if resource == "requirements" and len(parts) == 6 and method == "PATCH":
                requirement_id = int(parts[5])
                self._require_requirement(project_id, requirement_id)
                self.engineering.update_requirement(requirement_id, identifier=data.get("identifier"), title=data.get("title"), acceptance_criteria=data.get("acceptance_criteria"), priority=data.get("priority"), status=data.get("status"))
                current = next(item for item in self.engineering.list_requirements(project_id) if item["id"] == requirement_id)
                return self._json(200, current)
            if method == "GET" and resource == "sources":
                return self._json(200, self.engineering.list_sources(project_id))
            if method == "POST" and resource == "sources":
                file_id = data.get("file_id")
                if file_id is not None and self._workspace_file(project_id, int(file_id)) is None:
                    raise ValueError("File not found in project.")
                return self._json(201, {"id": self.engineering.create_source(project_id, data["title"], data["source_type"], author=data.get("author"), publisher=data.get("publisher"), version=data.get("version"), url=data.get("url"), file_id=file_id, checksum=data.get("checksum"))})
            if resource == "requirements" and len(parts) == 7 and parts[6] == "evidence":
                requirement_id = int(parts[5])
                self._require_requirement(project_id, requirement_id)
                if method == "GET":
                    return self._json(200, [self.engineering.get_evidence(e[0]) for e in db.get_evidence_history_for_requirement(requirement_id)])
                if method == "POST":
                    evidence_id = self.engineering.create_evidence(requirement_id, data["result"], data["supports_status"], source=data.get("source"), location=data.get("location"), calculation_record_id=data.get("calculation_record_id"), source_id=data.get("source_id"), classification=data.get("classification"), description=data.get("description"))
                    return self._json(201, {"id": evidence_id})
            if resource == "evidence" and len(parts) == 6 and method == "POST" and parts[5] == "invalidate":
                evidence_id = int(data["id"])
                evidence = self.engineering.get_evidence(evidence_id)
                if evidence is None:
                    raise ValueError("Evidence not found.")
                self._require_requirement(project_id, evidence["requirement_id"])
                self.engineering.invalidate_evidence(evidence_id, data["reason"])
                return self._json(200, {"invalidated": True})
            if method == "GET" and resource == "decisions":
                return self._json(200, self.engineering.list_decisions(project_id))
            if method == "POST" and resource == "decisions":
                if data.get("requirement_id") is not None:
                    self._require_requirement(project_id, int(data["requirement_id"]))
                return self._json(201, {"id": self.engineering.create_decision(project_id, data["title"], data["decision"], description=data.get("description"), requirement_id=data.get("requirement_id"), design_case_id=data.get("design_case_id"), rationale=data.get("rationale"))})
            return self._json(404, {"error": "Not found"})
        except (KeyError, ValueError, TypeError, json.JSONDecodeError) as exc:
            return self._json(400, {"error": str(exc) or "Invalid request"})
        except Exception as exc:
            return self._json(500, {"error": str(exc) or "Internal server error"})

    @staticmethod
    def _workspace_file(project_id: int, file_id: int):
        from workspace_storage import get_file
        row = get_file(file_id)
        return row if row is not None and row[1] == project_id else None

    def __call__(self, environ, start_response):
        target = environ.get("PATH_INFO", "/")
        if environ.get("QUERY_STRING"):
            target += "?" + environ["QUERY_STRING"]
        length = int(environ.get("CONTENT_LENGTH") or 0)
        body = environ["wsgi.input"].read(length) if length else b""
        status, headers, payload = self.request(environ.get("REQUEST_METHOD", "GET"), target, body)
        start_response(f"{status} {'OK' if status < 300 else 'Error'}", headers)
        return [payload]


def create_engineering_app(engineering: EngineeringApplication | None = None) -> EngineeringWebApplication:
    return EngineeringWebApplication(engineering)


__all__ = ["EngineeringWebApplication", "create_engineering_app"]
