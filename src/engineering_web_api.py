"""Project-scoped web boundary for engineering requirements and evidence."""
from __future__ import annotations

import base64
import json
from typing import Any
from urllib.parse import parse_qs, urlsplit

import db
import engineering_plans
import github_ingestion
import ingestion_service
import pdf_ingestion
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
        if row is None or int(row[1]) != project_id:
            raise ValueError("Requirement not found in project.")

    @staticmethod
    def _require_source(project_id: int, source_id: int) -> None:
        connection = db.get_connection()
        try:
            row = connection.execute(
                "SELECT id FROM sources WHERE id = ? AND project_id = ?",
                (source_id, project_id),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            raise ValueError("Source not found in project.")

    @staticmethod
    def _require_design_case(project_id: int, design_case_id: int) -> None:
        connection = db.get_connection()
        try:
            row = connection.execute(
                "SELECT id FROM design_cases WHERE id = ? AND project_id = ?",
                (design_case_id, project_id),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            raise ValueError("Design case not found in project.")

    @staticmethod
    def _require_evidence(project_id: int, evidence_id: int) -> None:
        connection = db.get_connection()
        try:
            row = connection.execute(
                """
                SELECT e.id
                FROM evidence e
                JOIN requirements r ON r.id = e.requirement_id
                WHERE e.id = ? AND r.project_id = ?
                """,
                (evidence_id, project_id),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            raise ValueError("Evidence not found in project.")

    @staticmethod
    def _workspace_file(project_id: int, file_id: int) -> Any:
        from workspace_storage import get_file

        row = get_file(file_id)
        return row if row is not None and int(row[1]) == project_id else None

    def _requirements_with_evidence(self, project_id: int) -> tuple[list[dict[str, object]], dict[int, list[dict[str, object]]]]:
        requirements = self.engineering.list_requirements(project_id)
        evidence_by_requirement: dict[int, list[dict[str, object]]] = {}
        for requirement in requirements:
            requirement_id = int(requirement["id"])
            evidence_items: list[dict[str, object]] = []
            for row in db.get_evidence_for_requirement(requirement_id):
                item = self.engineering.get_evidence(int(row[0]))
                if item is not None:
                    evidence_items.append(item)
            evidence_by_requirement[requirement_id] = evidence_items
        return requirements, evidence_by_requirement

    @staticmethod
    def _ingest_payload(project_id: int, data: dict[str, object], content: str, source_type: str) -> dict[str, object]:
        connection = db.get_connection()
        try:
            policy.require(connection, "local", "ingest_source")
            version_raw = data.get("version")
            url_raw = data.get("url")
            return ingestion_service.ingest_text(
                connection,
                project_id,
                str(data["title"]),
                content,
                source_type=source_type,
                version=None if version_raw is None else str(version_raw),
                url=None if url_raw is None else str(url_raw),
                chunk_chars=int(data.get("chunk_chars", ingestion_service.DEFAULT_CHUNK_CHARS)),
            )
        finally:
            connection.close()

    def _ingest_text(self, project_id: int, data: dict[str, object]) -> dict[str, object]:
        return self._ingest_payload(project_id, data, str(data["content"]), str(data.get("source_type", "text")))

    def _ingest_github(self, project_id: int, data: dict[str, object]) -> dict[str, object]:
        connection = db.get_connection()
        try:
            policy.require(connection, "local", "ingest_source")
            return github_ingestion.ingest_public_file(connection, project_id, str(data["url"]))
        finally:
            connection.close()

    def _ingest_pdf(self, project_id: int, data: dict[str, object]) -> dict[str, object]:
        encoded = data.get("data_base64")
        if not isinstance(encoded, str):
            raise ValueError("data_base64 is required for PDF ingestion.")
        try:
            payload = base64.b64decode(encoded, validate=True)
        except Exception as exc:
            raise ValueError("PDF data is not valid base64.") from exc
        text, page_count = pdf_ingestion.extract_pdf_text(payload)
        result = self._ingest_payload(project_id, data, text, "pdf")
        result["page_count"] = page_count
        result["bytes"] = len(payload)
        return result

    def _handle_requirements(self, method: str, parts: list[str], project_id: int, data: dict[str, object]) -> tuple[int, object] | None:
        if len(parts) == 5 and method == "GET":
            return 200, self.engineering.list_requirements(project_id)
        if len(parts) == 5 and method == "POST":
            return 201, {"id": db.create_requirement(project_id, str(data["description"]))}
        if len(parts) == 6 and parts[5] == "test-plan" and method == "GET":
            return 200, engineering_plans.build_test_plan(self.engineering.list_requirements(project_id))
        if len(parts) == 6 and method == "PATCH":
            requirement_id = int(parts[5])
            self._require_requirement(project_id, requirement_id)
            self.engineering.update_requirement(
                requirement_id,
                identifier=data.get("identifier"),
                title=data.get("title"),
                acceptance_criteria=data.get("acceptance_criteria"),
                priority=data.get("priority"),
                status=data.get("status"),
            )
            updated = next(item for item in self.engineering.list_requirements(project_id) if int(item["id"]) == requirement_id)
            return 200, updated
        if len(parts) == 7 and parts[6] == "evidence":
            requirement_id = int(parts[5])
            self._require_requirement(project_id, requirement_id)
            if method == "GET":
                connection = db.get_connection()
                try:
                    rows = connection.execute(
                        "SELECT id FROM evidence WHERE requirement_id = ? ORDER BY id",
                        (requirement_id,),
                    ).fetchall()
                finally:
                    connection.close()
                evidence: list[dict[str, object]] = []
                for row in rows:
                    item = self.engineering.get_evidence(int(row[0]))
                    if item is not None:
                        evidence.append(item)
                return 200, evidence
            if method == "POST":
                source_id_raw = data.get("source_id")
                source_id = int(source_id_raw) if source_id_raw is not None else None
                if source_id is not None:
                    self._require_source(project_id, source_id)
                evidence_id = self.engineering.create_evidence(
                    requirement_id,
                    str(data["result"]),
                    str(data["supports_status"]),
                    source=data.get("source"),
                    location=data.get("location"),
                    calculation_record_id=data.get("calculation_record_id"),
                    source_id=source_id,
                    classification=data.get("classification"),
                    description=data.get("description"),
                    evidence_type=data.get("evidence_type"),
                )
                return 201, {"id": evidence_id}
        return None

    def _handle_sources(self, method: str, parts: list[str], project_id: int, query: dict[str, str], data: dict[str, object]) -> tuple[int, object] | None:
        if len(parts) == 5 and method == "GET":
            return 200, self.engineering.list_sources(project_id)
        if len(parts) == 5 and method == "POST":
            file_id_raw = data.get("file_id")
            file_id = int(file_id_raw) if file_id_raw is not None else None
            if file_id is not None and self._workspace_file(project_id, file_id) is None:
                raise ValueError("File not found in project.")
            source_id = self.engineering.create_source(
                project_id,
                str(data["title"]),
                str(data["source_type"]),
                author=data.get("author"),
                publisher=data.get("publisher"),
                version=data.get("version"),
                url=data.get("url"),
                file_id=file_id,
                checksum=data.get("checksum"),
            )
            return 201, {"id": source_id}
        if len(parts) == 6 and parts[5] == "ingest" and method == "POST":
            return 201, self._ingest_text(project_id, data)
        if len(parts) == 6 and parts[5] == "github" and method == "POST":
            return 201, self._ingest_github(project_id, data)
        if len(parts) == 6 and parts[5] == "pdf" and method == "POST":
            return 201, self._ingest_pdf(project_id, data)
        if len(parts) == 6 and parts[5] == "search" and method == "GET":
            query_text = query.get("q", "").strip()
            if not query_text:
                raise ValueError("q is required.")
            limit = int(query.get("limit", "10"))
            connection = db.get_connection()
            try:
                return 200, ingestion_service.search_chunks(connection, project_id, query_text, limit)
            finally:
                connection.close()
        if len(parts) == 7 and parts[5] == "chunks" and method == "GET":
            chunk_id = int(parts[6])
            connection = db.get_connection()
            try:
                return 200, ingestion_service.get_chunk(connection, project_id, chunk_id)
            finally:
                connection.close()
        return None

    def _handle_other(self, method: str, parts: list[str], project_id: int, data: dict[str, object]) -> tuple[int, object] | None:
        resource = parts[4] if len(parts) > 4 else ""
        if resource == "report" and len(parts) == 5 and method == "GET":
            requirements, evidence_by_requirement = self._requirements_with_evidence(project_id)
            report = engineering_plans.build_weekly_report(
                requirements,
                self.engineering.list_sources(project_id),
                self.engineering.list_decisions(project_id),
                evidence_by_requirement,
            )
            return 200, report
        if resource == "evidence" and len(parts) == 6 and parts[5] == "invalidate" and method == "POST":
            evidence_id = int(data["id"])
            self._require_evidence(project_id, evidence_id)
            self.engineering.invalidate_evidence(evidence_id, str(data["reason"]))
            return 200, {"invalidated": True}
        if resource == "decisions" and len(parts) == 5 and method == "GET":
            return 200, self.engineering.list_decisions(project_id)
        if resource == "decisions" and len(parts) == 5 and method == "POST":
            requirement_raw = data.get("requirement_id")
            design_case_raw = data.get("design_case_id")
            requirement_id = int(requirement_raw) if requirement_raw is not None else None
            design_case_id = int(design_case_raw) if design_case_raw is not None else None
            if requirement_id is not None:
                self._require_requirement(project_id, requirement_id)
            if design_case_id is not None:
                self._require_design_case(project_id, design_case_id)
            decision_id = self.engineering.create_decision(
                project_id,
                str(data["title"]),
                str(data["decision"]),
                description=data.get("description"),
                requirement_id=requirement_id,
                design_case_id=design_case_id,
                rationale=data.get("rationale"),
            )
            return 201, {"id": decision_id}
        return None

    def request(self, method: str, target: str, body: bytes = b"") -> tuple[int, list[tuple[str, str]], bytes]:
        try:
            if len(body) > self.MAX_REQUEST_BODY_BYTES:
                return self._json(413, {"error": "Request body too large."})
            parsed = urlsplit(target)
            path = parsed.path.rstrip("/") or "/"
            query = {key: values[-1] for key, values in parse_qs(parsed.query).items()}
            raw_data = json.loads(body or b"{}")
            if not isinstance(raw_data, dict):
                raise ValueError("JSON request body must be an object.")
            parts = path.strip("/").split("/")
            if len(parts) < 4 or parts[:3] != ["api", "engineering", "projects"]:
                return self._json(404, {"error": "Not found"})
            project_id = int(parts[3])
            self._require_project(project_id)
            data = {str(key): value for key, value in raw_data.items()}

            resource = parts[4] if len(parts) > 4 else ""
            if resource == "requirements":
                handled = self._handle_requirements(method, parts, project_id, data)
            elif resource == "sources":
                handled = self._handle_sources(method, parts, project_id, query, data)
            else:
                handled = self._handle_other(method, parts, project_id, data)
            if handled is None:
                return self._json(404, {"error": "Not found"})
            return self._json(*handled)
        except PermissionError as exc:
            return self._json(403, {"error": str(exc) or "Permission denied"})
        except (KeyError, ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            return self._json(400, {"error": str(exc) or "Invalid request"})
        except Exception as exc:
            return self._json(500, {"error": str(exc) or "Internal server error"})

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
