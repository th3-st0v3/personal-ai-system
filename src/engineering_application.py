"""Application services for the engineering workspace domain.

This module provides a small, framework-neutral boundary over the engineering
schema. It keeps callers independent of SQLite rows while preserving the
existing calculation and workspace services.
"""

import json

import db
import engineering_plans
import engineering_schema
import workspace_storage
import auth_service
import uuid


class EngineeringApplication:
    """Coordinate engineering-domain use cases behind a stable interface."""

    def __init__(self):
        connection = db.get_connection()
        try:
            auth_service.initialize(connection)
            # Engineering sources may reference workspace files, so establish
            # the workspace-storage schema before the engineering schema.
            workspace_storage._initialize_schema(connection)
            engineering_schema.initialize(connection)
        finally:
            connection.close()

    @staticmethod
    def _workspace(row):
        return {
            "id": row[0], "name": row[1], "description": row[2],
            "status": row[3], "created_at": row[4], "updated_at": row[5],
        }

    @staticmethod
    def _user(row):
        return {
            "id": row[0], "name": row[1], "email": row[2],
            "status": row[3], "created_at": row[4],
        }

    @staticmethod
    def _project(row):
        return {
            "id": row[0], "name": row[1], "description": row[2],
            "created_at": row[3], "workspace_id": row[4], "owner_id": row[5],
            "status": row[6], "updated_at": row[7],
        }

    @staticmethod
    def _requirement(row) -> engineering_plans.RequirementRecord:
        return {
            "id": int(row[0]), "project_id": int(row[1]), "description": str(row[2]),
            "status": str(row[3]), "created_at": str(row[4]), "identifier": row[5],
            "title": row[6], "acceptance_criteria": row[7], "priority": row[8],
            "updated_at": str(row[9]),
        }

    @staticmethod
    def _source(row) -> dict[str, object]:
        return {
            "id": row[0], "project_id": row[1], "title": row[2], "author": row[3],
            "publisher": row[4], "source_type": row[5], "version": row[6],
            "url": row[7], "file_id": row[8], "checksum": row[9], "created_at": row[10],
        }

    @staticmethod
    def _evidence(row) -> dict[str, object]:
        return {
            "id": row[0], "requirement_id": row[1], "source": row[2],
            "location": row[3], "result": row[4], "supports_status": row[5],
            "lifecycle_status": row[6], "calculation_record_id": row[7],
            "source_id": row[8], "classification": row[9], "description": row[10],
            "invalidated_at": row[11], "invalidation_reason": row[12], "created_at": row[13],
            "evidence_type": row[14],
        }

    @staticmethod
    def _decision(row) -> dict[str, object]:
        return {
            "id": row[0], "project_id": row[1], "requirement_id": row[2],
            "design_case_id": row[3], "title": row[4], "description": row[5],
            "decision": row[6], "rationale": row[7], "status": row[8],
            "created_at": row[9], "updated_at": row[10],
        }

    @staticmethod
    def _require_text(value, field):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} must be a non-empty string.")
        return value.strip()

    @staticmethod
    def _require_status(status):
        if status not in {"Verified", "Failed", "Unverified", "At risk"}:
            raise ValueError("Invalid requirement status.")

    def create_workspace(self, name, description=None):
        name = self._require_text(name, "name")
        connection = db.get_connection()
        try:
            cursor = connection.execute(
                "INSERT INTO workspaces (name, description) VALUES (?, ?)",
                (name, description),
            )
            connection.commit()
            return cursor.lastrowid
        finally:
            connection.close()

    def list_workspaces(self):
        connection = db.get_connection()
        try:
            rows = connection.execute(
                "SELECT id, name, description, status, created_at, updated_at "
                "FROM workspaces ORDER BY id"
            ).fetchall()
            return [self._workspace(row) for row in rows]
        finally:
            connection.close()

    def create_user(self, name, email=None):
        name = self._require_text(name, "name")
        email_value = (
            self._require_text(email, "email")
            if email is not None
            else f"engineering-{uuid.uuid4().hex}@local.invalid"
        )
        connection = db.get_connection()
        try:
            cursor = connection.execute(
                "INSERT INTO users (name, email) VALUES (?, ?)",
                (name, email_value),
            )
            connection.commit()
            return cursor.lastrowid
        finally:
            connection.close()

    def list_workspace_members(self, workspace_id):
        connection = db.get_connection()
        try:
            rows = connection.execute(
                "SELECT u.id, u.name, u.email, u.status, u.created_at "
                "FROM users u JOIN workspace_members wm ON wm.user_id = u.id "
                "WHERE wm.workspace_id = ? ORDER BY u.id",
                (workspace_id,),
            ).fetchall()
            return [self._user(row) for row in rows]
        finally:
            connection.close()

    def add_workspace_member(self, workspace_id, user_id, role):
        role = self._require_text(role, "role")
        connection = db.get_connection()
        try:
            if connection.execute("SELECT id FROM workspaces WHERE id = ?", (workspace_id,)).fetchone() is None:
                raise ValueError(f"No workspace found with ID {workspace_id}.")
            if connection.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone() is None:
                raise ValueError(f"No user found with ID {user_id}.")
            connection.execute(
                "INSERT INTO workspace_members (workspace_id, user_id, role) VALUES (?, ?, ?)",
                (workspace_id, user_id, role),
            )
            connection.commit()
        finally:
            connection.close()

    def create_project(self, name, description=None):
        name = self._require_text(name, "name")
        connection = db.get_connection()
        try:
            cursor = connection.execute(
                "INSERT INTO projects (name, description) VALUES (?, ?)",
                (name, description),
            )
            connection.commit()
            return cursor.lastrowid
        finally:
            connection.close()

    def assign_project(self, project_id, workspace_id=None, owner_id=None, status="Active"):
        if status not in {"Active", "Archived", "Invalidated", "Superseded"}:
            raise ValueError("Invalid project status.")
        connection = db.get_connection()
        try:
            if connection.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone() is None:
                raise ValueError(f"No project found with ID {project_id}.")
            if workspace_id is not None and connection.execute("SELECT id FROM workspaces WHERE id = ?", (workspace_id,)).fetchone() is None:
                raise ValueError(f"No workspace found with ID {workspace_id}.")
            if owner_id is not None and connection.execute("SELECT id FROM users WHERE id = ?", (owner_id,)).fetchone() is None:
                raise ValueError(f"No user found with ID {owner_id}.")
            connection.execute(
                "UPDATE projects SET workspace_id = ?, owner_id = ?, status = ?, "
                "updated_at = datetime('now') WHERE id = ?",
                (workspace_id, owner_id, status, project_id),
            )
            connection.commit()
        finally:
            connection.close()

    def get_project(self, project_id):
        connection = db.get_connection()
        try:
            row = connection.execute(
                "SELECT id, name, description, created_at, workspace_id, owner_id, status, updated_at "
                "FROM projects WHERE id = ?",
                (project_id,),
            ).fetchone()
            return None if row is None else self._project(row)
        finally:
            connection.close()

    def list_requirements(self, project_id: int) -> list[engineering_plans.RequirementRecord]:
        connection = db.get_connection()
        try:
            rows = connection.execute(
                "SELECT id, project_id, description, status, created_at, identifier, title, "
                "acceptance_criteria, priority, updated_at FROM requirements "
                "WHERE project_id = ? ORDER BY id",
                (project_id,),
            ).fetchall()
            return [self._requirement(row) for row in rows]
        finally:
            connection.close()

    def update_requirement(self, requirement_id, *, identifier=None, title=None,
                           acceptance_criteria=None, priority=None, status=None):
        if status is not None:
            self._require_status(status)
        updates = {
            "identifier": identifier,
            "title": title,
            "acceptance_criteria": acceptance_criteria,
            "priority": priority,
            "status": status,
        }
        changed = {key: value for key, value in updates.items() if value is not None}
        if not changed:
            raise ValueError("At least one requirement field must be provided.")
        connection = db.get_connection()
        try:
            if connection.execute("SELECT id FROM requirements WHERE id = ?", (requirement_id,)).fetchone() is None:
                raise ValueError(f"No requirement found with ID {requirement_id}.")
            assignments = ", ".join(f"{key} = ?" for key in changed)
            values = list(changed.values()) + [requirement_id]
            connection.execute(
                f"UPDATE requirements SET {assignments}, updated_at = datetime('now') WHERE id = ?",
                values,
            )
            connection.commit()
        finally:
            connection.close()

    def create_source(self, project_id, title, source_type, *, author=None, publisher=None,
                      version=None, url=None, file_id=None, checksum=None):
        title = self._require_text(title, "title")
        source_type = self._require_text(source_type, "source_type")
        connection = db.get_connection()
        try:
            if connection.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone() is None:
                raise ValueError(f"No project found with ID {project_id}.")
            if file_id is not None and connection.execute("SELECT id FROM files WHERE id = ? AND project_id = ?", (file_id, project_id)).fetchone() is None:
                raise ValueError("File not found in project.")
            cursor = connection.execute(
                "INSERT INTO sources (project_id, title, author, publisher, source_type, "
                "version, url, file_id, checksum) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (project_id, title, author, publisher, source_type,
                 version, url, file_id, checksum),
            )
            connection.commit()
            return cursor.lastrowid
        finally:
            connection.close()

    def list_sources(self, project_id) -> list[dict[str, object]]:
        connection = db.get_connection()
        try:
            rows = connection.execute(
                "SELECT id, project_id, title, author, publisher, source_type, version, "
                "url, file_id, checksum, created_at FROM sources WHERE project_id = ? ORDER BY id",
                (project_id,),
            ).fetchall()
            return [self._source(row) for row in rows]
        finally:
            connection.close()

    def create_evidence(self, requirement_id, result, supports_status, *, source=None,
                        location=None, calculation_record_id=None, source_id=None,
                        classification=None, description=None, evidence_type=None):
        self._require_status(supports_status)
        evidence_type = evidence_type or ("calculation" if calculation_record_id is not None else "manual_entry")
        if evidence_type not in engineering_schema.EVIDENCE_TYPES:
            raise ValueError("Invalid evidence type.")
        connection = db.get_connection()
        try:
            requirement = connection.execute("SELECT id, project_id FROM requirements WHERE id = ?", (requirement_id,)).fetchone()
            if requirement is None:
                raise ValueError(f"No requirement found with ID {requirement_id}.")
            project_id = requirement[1]
            if source_id is not None and connection.execute("SELECT id FROM sources WHERE id = ? AND project_id = ?", (source_id, project_id)).fetchone() is None:
                raise ValueError("Source not found in project.")
            if calculation_record_id is not None and connection.execute("SELECT id FROM calculation_records WHERE id = ?", (calculation_record_id,)).fetchone() is None:
                raise ValueError(f"No calculation record found with ID {calculation_record_id}.")
            if evidence_type == "calculation" and calculation_record_id is None:
                raise ValueError("Calculation evidence requires calculation_record_id.")
            cursor = connection.execute(
                "INSERT INTO evidence (requirement_id, source, location, result, supports_status, "
                "calculation_record_id, source_id, classification, description, evidence_type) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (requirement_id, source, location, result, supports_status,
                 calculation_record_id, source_id, classification, description, evidence_type),
            )
            connection.commit()
            return cursor.lastrowid
        finally:
            connection.close()

    def get_evidence(self, evidence_id):
        connection = db.get_connection()
        try:
            row = connection.execute(
                "SELECT id, requirement_id, source, location, result, supports_status, "
                "lifecycle_status, calculation_record_id, source_id, classification, description, "
                "invalidated_at, invalidation_reason, created_at, evidence_type FROM evidence WHERE id = ?",
                (evidence_id,),
            ).fetchone()
            return None if row is None else self._evidence(row)
        finally:
            connection.close()

    def invalidate_evidence(self, evidence_id, reason):
        reason = self._require_text(reason, "reason")
        connection = db.get_connection()
        try:
            if connection.execute("SELECT id FROM evidence WHERE id = ?", (evidence_id,)).fetchone() is None:
                raise ValueError(f"No evidence found with ID {evidence_id}.")
            connection.execute(
                "UPDATE evidence SET lifecycle_status = 'Invalidated', invalidated_at = datetime('now'), "
                "invalidation_reason = ? WHERE id = ?",
                (reason, evidence_id),
            )
            connection.commit()
        finally:
            connection.close()

    def create_decision(self, project_id, title, decision, *, description=None,
                        requirement_id=None, design_case_id=None, rationale=None):
        title = self._require_text(title, "title")
        decision = self._require_text(decision, "decision")
        connection = db.get_connection()
        try:
            if connection.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone() is None:
                raise ValueError(f"No project found with ID {project_id}.")
            if requirement_id is not None and connection.execute("SELECT id FROM requirements WHERE id = ? AND project_id = ?", (requirement_id, project_id)).fetchone() is None:
                raise ValueError("Requirement not found in project.")
            if design_case_id is not None and connection.execute("SELECT id FROM design_cases WHERE id = ? AND project_id = ?", (design_case_id, project_id)).fetchone() is None:
                raise ValueError("Design case not found in project.")
            cursor = connection.execute(
                "INSERT INTO decisions (project_id, requirement_id, design_case_id, title, "
                "description, decision, rationale) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (project_id, requirement_id, design_case_id, title, description, decision, rationale),
            )
            connection.commit()
            return cursor.lastrowid
        finally:
            connection.close()

    def list_decisions(self, project_id) -> list[dict[str, object]]:
        connection = db.get_connection()
        try:
            rows = connection.execute(
                "SELECT id, project_id, requirement_id, design_case_id, title, description, "
                "decision, rationale, status, created_at, updated_at "
                "FROM decisions WHERE project_id = ? ORDER BY id",
                (project_id,),
            ).fetchall()
            return [self._decision(row) for row in rows]
        finally:
            connection.close()

    def get_decision(self, decision_id):
        connection = db.get_connection()
        try:
            row = connection.execute(
                "SELECT id, project_id, requirement_id, design_case_id, title, description, "
                "decision, rationale, status, created_at, updated_at FROM decisions WHERE id = ?",
                (decision_id,),
            ).fetchone()
            return None if row is None else self._decision(row)
        finally:
            connection.close()

    def update_decision(self, decision_id, *, decision=None, rationale=None, status=None):
        if status is not None and status not in {"Proposed", "Accepted", "Rejected", "Superseded"}:
            raise ValueError("Invalid decision status.")
        changed = {key: value for key, value in {"decision": decision, "rationale": rationale, "status": status}.items() if value is not None}
        if not changed:
            raise ValueError("At least one decision field must be provided.")
        connection = db.get_connection()
        try:
            if connection.execute("SELECT id FROM decisions WHERE id = ?", (decision_id,)).fetchone() is None:
                raise ValueError(f"No decision found with ID {decision_id}.")
            assignments = ", ".join(f"{key} = ?" for key in changed)
            values = list(changed.values()) + [decision_id]
            connection.execute(
                f"UPDATE decisions SET {assignments}, updated_at = datetime('now') WHERE id = ?",
                values,
            )
            connection.commit()
        finally:
            connection.close()

    def list_design_cases(self, project_id):
        connection = db.get_connection()
        try:
            rows = connection.execute(
                "SELECT id, project_id, well_id, name, description, status, created_at, updated_at "
                "FROM design_cases WHERE project_id = ? ORDER BY id",
                (project_id,),
            ).fetchall()
            return [{
                "id": row[0], "project_id": row[1], "well_id": row[2], "name": row[3],
                "description": row[4], "status": row[5], "created_at": row[6], "updated_at": row[7],
            } for row in rows]
        finally:
            connection.close()

    def list_wells(self, project_id):
        connection = db.get_connection()
        try:
            rows = connection.execute(
                "SELECT id, project_id, identifier, name, description, status, created_at, updated_at "
                "FROM wells WHERE project_id = ? ORDER BY id",
                (project_id,),
            ).fetchall()
            return [{
                "id": row[0], "project_id": row[1], "identifier": row[2], "name": row[3],
                "description": row[4], "status": row[5], "created_at": row[6], "updated_at": row[7],
            } for row in rows]
        finally:
            connection.close()

    def record_audit_event(self, entity_type, entity_id, action, *, workspace_id=None,
                           user_id=None, metadata=None):
        entity_type = self._require_text(entity_type, "entity_type")
        action = self._require_text(action, "action")
        connection = db.get_connection()
        try:
            if workspace_id is not None and connection.execute("SELECT id FROM workspaces WHERE id = ?", (workspace_id,)).fetchone() is None:
                raise ValueError(f"No workspace found with ID {workspace_id}.")
            if user_id is not None and connection.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone() is None:
                raise ValueError(f"No user found with ID {user_id}.")
            cursor = connection.execute(
                "INSERT INTO audit_events (workspace_id, user_id, entity_type, entity_id, action, metadata) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (workspace_id, user_id, entity_type, entity_id, action,
                 None if metadata is None else json.dumps(metadata, sort_keys=True)),
            )
            connection.commit()
            return cursor.lastrowid
        finally:
            connection.close()

__all__ = ["EngineeringApplication"]
