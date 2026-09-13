"""Project-scoped web boundary for engineering requirements and evidence."""
from __future__ import annotations

import json
from urllib.parse import parse_qs, urlsplit

import db
import engineering_plans
import ingestion_service
import policy
from engineering_application import EngineeringApplication


class EngineeringWebApplication:
    """Expose engineering evidence workflows without coupling them to the core workspace API."""

    MAX_REQUEST_BODY_BYTES = 4 * 1024 * 1024

    def __init__(self, engineering: EngineeringApplication | None = None):
        self.engineering = engineering or EngineeringApplication()

    @staticmethod
    def _json(status: int, body: object) -> tuple[int, list[tuple[str, str]], bytes]:
        payload = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
        return status, [("Content-Type", "application/json; charset=utf-8"), ("Content-Length", str(len(payload)))], payload

    @staticmethod
    def _require_project(project_id: int) -> None:
        connection = db.get_connection()
        try:
            row = connection.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
        finally:
            connection.close()
        if row is None:
            raise ValueError(f"No project found with ID {project_id}.")

    @staticmethod
    def _require_requirement(project_id: int, requirement_id: int) -> None:
        row = db.get_requirement(requirement_id)
        if row is None or row[1] != project_id:
            raise ValueError("Requirement not found in project.")

    @staticmethod
    def _require_source(project_id: int, source_id: int) -> None:
        connection = db.get_connection()
        try:
            row = connection.execute("SELECT id FROM sources WHERE id = ? AND project_id = ?", (source_id, project_id)).fetchone()
        finally:
            connection.close()
        if row is None:
            raise ValueError("Source not found in project.")

    @staticmethod
    def _require_design_case(project_id: int, design_case_id: int) -> None:
        connection = db.get_connection()
        try:
            row = connection.execute("SELECT id FROM design_cases WHERE id = ? AND project_id = ?", (design_case_id, project_id)).fetchone()
        finally:
            connection.close()
        if row is None:
            raise ValueError("Design case not found in project.")

    @staticmethod
    def _require_evidence(project_id: int, evidence_id: int) -> None:
        connection = db.get_connection()
        try:
            row = connection.execute("SELECT e.id FROM evidence e JOIN requirements r ON r.id = e.requirement_id WHERE e.id = ? AND r.project_id = ?", (evidence_id, project_id)).fetchone()
        finally:
            connection.close()
        if row is None:
            raise ValueError("Evidence not found in project.")

    def _requirements_with_evidence(self, project_id: int) -> tuple[list[dict[str, object]], dict[int, list[dict[str, object]]]]:
        requirements = self.engineering.list_requirements(project_id)
        evidence_by_requirement: dict[int, list[dict[str, object]]] = {}
        for requirement in requirements:
            evidence_by_requirement[int(requirement["id"])] = [
                self.engineering.get_evidence(row[0])
                for row in db.get_evidence_for_requirement(int(requirement["id"]))
            ]
        return requirements, evidence_by_requirement

    def request(self, method: str, target: str, body: bytes = b"") -> tuple[int, list[tuple[str, str]], bytes]:
        try:
            if len(body) > self.MAX_REQUEST_BODY_BYTES:
                return self._json(413, {"error": "Request body too large."})
            parsed = urlsplit(target)
            path = parsed.path.rstrip("/") or "/"
            query = {key: values[-1] for key, values in parse_qs(parsed.query).items()}
            data = json.loads(body or b"{}")
            if not isinstance(data, dict):
                raise ValueError("JSON request body must be an object.")
            parts = path.strip("/").split("/")
            if len(parts) < 4 or parts[:3] != ["api", "engineering", "projects"]:
                return self._json(404, {"error": "Not found"})
            project_id = int(parts[3])
            self._require_project(project_id)
            resource = parts[4] if len(parts) > 4 else ""
            if method == "GET" and len(parts) == 5 and resource == "requirements":
                return self._json(200, self.engineering.list_requirements(project_id))
            if method == "POST" and len(parts) == 5 and resource == "requirements":
                return self._json(201, {"id": db.create_requirement(project_id, data["description"])})
            if method == "GET" and len(parts) == 6 and resource == "requirements" and parts[5] == "test-plan":
                return self._json(200, engineering_plans.build_test_plan(self.engineering.list_requirements(project_id)))
            if resource == "requirements" and len(parts) == 6 and method == "PATCH":
                requirement_id = int(parts[5])
                self._require_requirement(project_id, requirement_id)
                self.engineering.update_requirement(requirement_id, identifier=data.get("identifier"), title=data.get("title"), acceptance_criteria=data.get("acceptance_criteria"), priority=data.get("priority"), status=data.get("status"))
                current = next(item for item in self.engineering.list_requirements(project_id) if item["id"] == requirement_id)
                return self._json(200, current)
            if method == "GET" and len(parts) == 5 and resource == "sources":
                return self._json(200, self.engineering.list_sources(project_id))
            if method == "POST" and len(parts) == 5 and resource == "sources":
                file_id = data.get("file_id")
                if file_id is not None and self._workspace_file(project_id, int(file_id)) is None:
                    raise ValueError("File not found in project.")
                return self._json(201, {"id": self.engineering.create_source(project_id, data["title"], data["source_type"], author=data.get("author"), publisher=data.get("publisher"), version=data.get("version"), url=data.get("url"), file_id=file_id, checksum=data.get("checksum"))})
            if method == "POST" and len(parts) == 6 and resource == "sources" and parts[5] == "ingest":
                connection = db.get_connection()
                try:
                    policy.require(connection, "local", "ingest_source")
                    result = ingestion_service.ingest_text(connection, project_id, data["title"], data["content"], source_type=data.get("source_type", "text"), version=data.get("version"), url=data.get("url"), chunk_chars=int(data.get("chunk_chars", ingestion_service.DEFAULT_CHUNK_CHARS)))
                finally:
                    connection.close()
                return self._json(201, result)
            if method == "GET" and len(parts) == 6 and resource == "sources" and parts[5] == "search":
                connection = db.get_connection()
                try:
                    results = ingestion_service.search_chunks(connection, project_id, query["q"], int(query.get("limit", "10")))
                finally:
                    connection.close()
                return self._json(200, results)
            if method == "GET" and len(parts) == 5 and resource == "report":
                requirements, evidence_by_requirement = self._requirements_with_evidence(project_id)
                return self._json(200, engineering_plans.build_weekly_report(requirements, self.engineering.list_sources(project_id), self.engineering.list_decisions(project_id), evidence_by_requirement))
            if resource == "requirements" and len(parts) == 7 and parts[6] == "evidence":
                requirement_id = int(parts[5])
                self._require_requirement(project_id, requirement_id)
                if method == "GET":
                    connection = db.get_connection()
                    try:
                        evidence_ids = [row[0] for row in connection.execute("SELECT id FROM evidence WHERE requirement_id = ? ORDER BY id", (requirement_id,)).fetchall()]
                    finally:
                        connection.close()
                    return self._json(200, [self.engineering.get_evidence(evidence_id) for evidence_id in evidence_ids])
                if method == "POST":
                    source_id = data.get("source_id")
                    if source_id is not None:
                        self._require_source(project_id, int(source_id))
                    evidence_id = self.engineering.create_evidence(requirement_id, data["result"], data["supports_status"], source=data.get("source"), location=data.get("location"), calculation_record_id=data.get("calculation_record_id"), source_id=source_id, classification=data.get("classification"), description=data.get("description"))
                    return self._json(201, {"id": evidence_id})
            if resource == "evidence" and len(parts) == 6 and method == "POST" and parts[5] == "invalidate":
                evidence_id = int(data["id"])
                self._require_evidence(project_id, evidence_id)
                self.engineering.invalidate_evidence(evidence_id, data["reason"])
                return self._json(200, {"invalidated": True})
            if method == "GET" and len(parts) == 5 and resource == "decisions":
                return self._json(200, self.engineering.list_decisions(project_id))
            if method == "POST" and len(parts) == 5 and resource == "decisions":
                requirement_id = data.get("requirement_id")
                design_case_id = data.get("design_case_id")
                if requirement_id is not None:
                    self._require_requirement(project_id, int(requirement_id))
                if design_case_id is not None:
                    self._require_design_case(project_id, int(design_case_id))
                return self._json(201, {"id": self.engineering.create_decision(project_id, data["title"], data["decision"], description=data.get("description"), requirement_id=requirement_id, design_case_id=design_case_id, rationale=data.get("rationale"))})
            return self._json(404, {"error": "Not found"})
        except PermissionError as exc:
            return self._json(403, {"error": str(exc) or "Permission denied"})
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
        try:
            length = int(environ.get("CONTENT_LENGTH") or 0)
            if length < 0:
                raise ValueError("Content length cannot be negative.")
            if length > self.MAX_REQUEST_BODY_BYTES:
                status, headers, payload = self._json(413, {"error": "Request body too large."})
            else:
                target = environ.get("PATH_INFO", "/")
                if environ.get("QUERY_STRING"):
                    target += "?" + environ["QUERY_STRING"]
                body = environ["wsgi.input"].read(length) if length else b""
                status, headers, payload = self.request(environ.get("REQUEST_METHOD", "GET"), target, body)
        except (TypeError, ValueError) as exc:
            status, headers, payload = self._json(400, {"error": str(exc) or "Invalid request"})
        start_response(f"{status} {'OK' if status < 300 else 'Error'}", headers)
        return [payload]


def create_engineering_app(engineering: EngineeringApplication | None = None) -> EngineeringWebApplication:
    return EngineeringWebApplication(engineering)


__all__ = ["EngineeringWebApplication", "create_engineering_app"]
