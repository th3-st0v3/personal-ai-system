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
    def _as_int(value: object, field: str) -> int:
        """Convert a JSON/query value to an integer while narrowing its static type."""
        if isinstance(value, bool):
            raise ValueError(f"{field} must be an integer.")
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            try:
                return int(value)
            except ValueError as exc:
                raise ValueError(f"{field} must be an integer.") from exc
        raise ValueError(f"{field} must be an integer.")

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

    def _requirements_with_evidence(
        self, project_id: int
    ) -> tuple[list[engineering_plans.RequirementRecord], dict[int, list[dict[str, object]]]]:
        requirements = self.engineering.list_requirements(project_id)
        evidence_by_requirement: dict[int, list[dict[str, object]]] = {}
        for requirement in requirements:
            requirement_id = self._as_int(requirement["id"], "requirement_id")
            evidence_items: list[dict[str, object]] = []
            for row in db.get_evidence_for_requirement(requirement_id):
                item = self.engineering.get_evidence(int(row[0]))
                if item is not None:
                    evidence_items.append(item)
            evidence_by_requirement[requirement_id] = evidence_items
        return requirements, evidence_by_requirement

    def _ingest_payload(self, project_id: int, data: dict[str, object], content: str, source_type: str) -> dict[str, object]:
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
                chunk_chars=self._as_int(data.get("chunk_chars", ingestion_service.DEFAULT_CHUNK_CHARS), "chunk_chars"),
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

    def _requirement_history(self, project_id: int, requirement_id: int) -> list[dict[str, object]]:
        """Build a backend-authoritative requirement verification timeline.

        The timeline is derived from persisted engineering records only:
        requirement timestamps/status, evidence lifecycle timestamps, linked
        decisions, reviews, and audit records. No synthetic client state is
        accepted as history.
        """
        self._require_requirement(project_id, requirement_id)
        connection = db.get_connection()
        try:
            rows = connection.execute(
                """
                SELECT
                    e.id,
                    e.result,
                    e.supports_status,
                    e.lifecycle_status,
                    e.source,
                    e.location,
                    e.source_id,
                    e.calculation_record_id,
                    e.description,
                    e.evidence_type,
                    e.created_at,
                    e.invalidated_at,
                    e.invalidation_reason
                FROM evidence e
                WHERE e.requirement_id = ?
                ORDER BY e.created_at ASC, e.id ASC
                """,
                (requirement_id,),
            ).fetchall()

            evidence_events: list[dict[str, object]] = []
            for row in rows:
                source = None
                if row[6] is not None:
                    source_row = connection.execute(
                        """
                        SELECT id, title, source_type, version, url
                        FROM sources
                        WHERE id = ? AND project_id = ?
                        """,
                        (row[6], project_id),
                    ).fetchone()
                    if source_row is not None:
                        source = {
                            "id": source_row[0],
                            "title": source_row[1],
                            "source_type": source_row[2],
                            "version": source_row[3],
                            "url": source_row[4],
                        }

                evidence_events.append({
                    "id": f"evidence-{row[0]}",
                    "entity_type": "evidence",
                    "entity_id": row[0],
                    "event_type": "evidence_recorded",
                    "occurred_at": row[10],
                    "status": row[2],
                    "lifecycle_status": row[3],
                    "title": "Evidence recorded",
                    "description": row[8] or row[1] or "Evidence was recorded.",
                    "result": row[1],
                    "location": row[5],
                    "evidence_type": row[9],
                    "calculation_record_id": row[7],
                    "source": source or ({"title": row[4], "external": True} if row[4] else None),
                })
                if row[11]:
                    evidence_events.append({
                        "id": f"evidence-{row[0]}-invalidated",
                        "entity_type": "evidence",
                        "entity_id": row[0],
                        "event_type": "evidence_invalidated",
                        "occurred_at": row[11],
                        "status": "Invalidated",
                        "lifecycle_status": "Invalidated",
                        "title": "Evidence invalidated",
                        "description": row[12] or "Evidence was invalidated.",
                        "result": row[1],
                        "source": source or ({"title": row[4], "external": True} if row[4] else None),
                    })

            decision_rows = connection.execute(
                """
                SELECT id, title, decision, rationale, status, created_at, updated_at
                FROM decisions
                WHERE project_id = ? AND requirement_id = ?
                ORDER BY created_at ASC, id ASC
                """,
                (project_id, requirement_id),
            ).fetchall()

            decision_events = [{
                "id": f"decision-{row[0]}",
                "entity_type": "decision",
                "entity_id": row[0],
                "event_type": "decision_recorded",
                "occurred_at": row[5],
                "status": row[4],
                "title": row[1] or "Decision recorded",
                "description": row[2] or "A decision was linked to this requirement.",
                "rationale": row[3],
                "updated_at": row[6],
            } for row in decision_rows]

            review_rows = connection.execute(
                """
                SELECT id, status, comments, created_at, completed_at
                FROM reviews
                WHERE entity_type = 'requirement' AND entity_id = ?
                ORDER BY created_at ASC, id ASC
                """,
                (requirement_id,),
            ).fetchall()
            review_events = [{
                "id": f"review-{row[0]}",
                "entity_type": "review",
                "entity_id": row[0],
                "event_type": "review",
                "occurred_at": row[4] or row[3],
                "status": row[1],
                "title": "Requirement review",
                "description": row[2] or f"Review status: {row[1]}.",
            } for row in review_rows]

            audit_rows = connection.execute(
                """
                SELECT id, action, metadata, created_at
                FROM audit_events
                WHERE entity_type = 'requirement' AND entity_id = ?
                ORDER BY created_at ASC, id ASC
                """,
                (requirement_id,),
            ).fetchall()

            audit_events: list[dict[str, object]] = []
            for row in audit_rows:
                metadata: object = None
                if row[2]:
                    try:
                        metadata = json.loads(row[2])
                    except (TypeError, json.JSONDecodeError):
                        metadata = {"raw": row[2]}
                audit_events.append({
                    "id": f"audit-{row[0]}",
                    "entity_type": "audit",
                    "entity_id": requirement_id,
                    "event_type": "audit",
                    "occurred_at": row[3],
                    "status": None,
                    "title": row[1],
                    "description": row[1],
                    "metadata": metadata,
                })

            requirement_record = next(
                item for item in self.engineering.list_requirements(project_id)
                if int(item["id"]) == requirement_id
            )
            requirement_event = [{
                "id": f"requirement-{requirement_id}-updated",
                "entity_type": "requirement",
                "entity_id": requirement_id,
                "event_type": "requirement_record",
                "occurred_at": requirement_record.get("updated_at") or requirement_record.get("created_at"),
                "status": requirement_record.get("status"),
                "title": "Requirement record",
                "description": "Current persisted requirement record.",
            }]

            events = [*requirement_event, *evidence_events, *decision_events, *review_events, *audit_events]
            events.sort(key=lambda item: (str(item.get("occurred_at") or ""), str(item.get("id") or "")), reverse=True)
            return events
        finally:
            connection.close()

    def _handle_requirements(self, method: str, parts: list[str], project_id: int, data: dict[str, object]) -> tuple[int, object] | None:
        if len(parts) == 5 and method == "GET":
            return 200, self.engineering.list_requirements(project_id)
        if len(parts) == 5 and method == "POST":
            return 201, {"id": db.create_requirement(project_id, str(data["description"]))}
        if len(parts) == 6 and parts[5] == "test-plan" and method == "GET":
            return 200, engineering_plans.build_test_plan(self.engineering.list_requirements(project_id))
        if len(parts) == 7 and parts[6] == "history" and method == "GET":
            requirement_id = self._as_int(parts[5], "requirement_id")
            return 200, self._requirement_history(project_id, requirement_id)
        if len(parts) == 6 and method == "PATCH":
            requirement_id = self._as_int(parts[5], "requirement_id")
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
            requirement_id = self._as_int(parts[5], "requirement_id")
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
                source_id = self._as_int(source_id_raw, "source_id") if source_id_raw is not None else None
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
            file_id = self._as_int(file_id_raw, "file_id") if file_id_raw is not None else None
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
            limit = self._as_int(query.get("limit", "10"), "limit")
            connection = db.get_connection()
            try:
                return 200, ingestion_service.search_chunks(connection, project_id, query_text, limit)
            finally:
                connection.close()
        if len(parts) == 7 and parts[5] == "chunks" and method == "GET":
            chunk_id = self._as_int(parts[6], "chunk_id")
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
            evidence_id = self._as_int(data["id"], "evidence_id")
            self._require_evidence(project_id, evidence_id)
            self.engineering.invalidate_evidence(evidence_id, str(data["reason"]))
            return 200, {"invalidated": True}
        if resource == "decisions" and len(parts) == 5 and method == "GET":
            return 200, self.engineering.list_decisions(project_id)
        if resource == "decisions" and len(parts) == 5 and method == "POST":
            requirement_raw = data.get("requirement_id")
            design_case_raw = data.get("design_case_id")
            requirement_id = self._as_int(requirement_raw, "requirement_id") if requirement_raw is not None else None
            design_case_id = self._as_int(design_case_raw, "design_case_id") if design_case_raw is not None else None
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
            project_id = self._as_int(parts[3], "project_id")
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
            length = self._as_int(environ.get("CONTENT_LENGTH") or 0, "content_length")
            if length < 0:
                raise ValueError("Content length cannot be negative.")
            if length > self.MAX_REQUEST_BODY_BYTES:
                status, headers, payload = self._json(413, {"error": "Request body too large."})
            else:
                target = environ.get("PATH_INFO", "/")
                if environ.get("QUERY_STRING"):
                    target += "?" + environ["QUERY_STRING"]
                body_stream = environ["wsgi.input"]
                body = body_stream.read(length) if hasattr(body_stream, "read") and length else b""
                status, headers, payload = self.request(environ.get("REQUEST_METHOD", "GET"), target, body)
        except (TypeError, ValueError) as exc:
            status, headers, payload = self._json(400, {"error": str(exc) or "Invalid request"})
        start_response(f"{status} {'OK' if status < 300 else 'Error'}", headers)
        return [payload]


def create_engineering_app(engineering: EngineeringApplication | None = None) -> EngineeringWebApplication:
    return EngineeringWebApplication(engineering)


__all__ = ["EngineeringWebApplication", "create_engineering_app"]
