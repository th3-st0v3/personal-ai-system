"""Application services for the engineering workspace domain.

This module provides a small, framework-neutral boundary over the engineering
schema. It keeps callers independent of SQLite rows while preserving the
existing calculation and workspace services.
"""

import json

import db
import engineering_schema
import workspace_storage


class EngineeringApplication:
    """Coordinate engineering-domain use cases behind a stable interface."""

    def __init__(self):
        connection = db.get_connection()
        try:
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
    def _requirement(row):
        return {
            "id": row[0], "project_id": row[1], "description": row[2],
            "status": row[3], "created_at": row[4], "identifier": row[5],
            "title": row[6], "acceptance_criteria": row[7], "priority": row[8],
            "updated_at": row[9],
        }

    @staticmethod
    def _source(row):
        return {
            "id": row[0], "project_id": row[1], "title": row[2], "author": row[3],
            "publisher": row[4], "source_type": row[5], "version": row[6],
            "url": row[7], "file_id": row[8], "checksum": row[9], "created_at": row[10],
        }

    @staticmethod
    def _evidence(row):
        return {
            "id": row[0], "requirement_id": row[1], "source": row[2],
            "location": row[3], "result": row[4], "supports_status": row[5],
            "lifecycle_status": row[6], "calculation_record_id": row[7],
            "source_id": row[8], "classification": row[9], "description": row[10],
            "invalidated_at": row[11], "invalidation_reason": row[12], "created_at": row[13],
        }

    @staticmethod
    def _decision(row):
        return {
            "id": row[0], "project_id": row[1], "requirement_id": row[2],
            "design_case_id": row[3], "title": row[4], "description": row[5],
            "decision": row[6], "rationale": row[7], "status": row[8],
            "created_at": row[9], "updated_at": row[10],
        }

    def create_workspace(self, name, description=None):
        connection = db.get_connection()
        try:
            cursor = connection.execute(
                "INSERT INTO workspaces (name, description) VALUES (?, ?)",
                (name.strip(), description),
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
        connection = db.get_connection()
        try:
            cursor = connection.execute(
                "INSERT INTO users (name, email) VALUES (?, ?)",
                (name.strip(), email),
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
        connection = db.get_connection()
        try:
            connection.execute(
                "INSERT INTO workspace_members (workspace_id, user_id, role) VALUES (?, ?, ?)",
                (workspace_id, user_id, role),
            )
            connection.commit()
        finally:
            connection.close()

    def create_project(self, name, description=None):
        connection = db.get_connection()
        try:
            cursor = connection.execute(
                "INSERT INTO projects (name, description) VALUES (?, ?)",
                (name.strip(), description),
            )
            connection.commit()
            return cursor.lastrowid
        finally:
            connection.close()

    def assign_project(self, project_id, workspace_id=None, owner_id=None, status="Active"):
        connection = db.get_connection()
        try:
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

    def list_requirements(self, project_id):
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
        allowed_statuses = {"Verified", "Failed", "Unverified", "At risk"}
        if status is not None and status not in allowed_statuses:
            raise ValueError("Invalid requirement status.")
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
        connection = db.get_connection()
        try:
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

    def list_sources(self, project_id):
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
                        classification=None, description=None):
        connection = db.get_connection()
        try:
            cursor = connection.execute(
                "INSERT INTO evidence (requirement_id, source, location, result, supports_status, "
                "calculation_record_id, source_id, classification, description) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (requirement_id, source, location, result, supports_status,
                 calculation_record_id, source_id, classification, description),
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
                "invalidated_at, invalidation_reason, created_at FROM evidence WHERE id = ?",
                (evidence_id,),
            ).fetchone()
            return None if row is None else self._evidence(row)
        finally:
            connection.close()

    def invalidate_evidence(self, evidence_id, reason):
        connection = db.get_connection()
        try:
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
        connection = db.get_connection()
        try:
            cursor = connection.execute(
                "INSERT INTO decisions (project_id, requirement_id, design_case_id, title, "
                "description, decision, rationale) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (project_id, requirement_id, design_case_id, title, description, decision, rationale),
            )
            connection.commit()
            return cursor.lastrowid
        finally:
            connection.close()

    def list_decisions(self, project_id):
        connection = db.get_connection()
        try:
            rows = connection.execute(
                "SELECT id, project_id, requirement_id, design_case_id, title, description, "
                "decision, rationale, status, created_at, updated_at FROM decisions "
                "WHERE project_id = ? ORDER BY id",
                (project_id,),
            ).fetchall()
            return [self._decision(row) for row in rows]
        finally:
            connection.close()

    def record_audit_event(self, entity_type, entity_id, action, *, workspace_id=None,
                           user_id=None, metadata=None):
        connection = db.get_connection()
        try:
            connection.execute(
                "INSERT INTO audit_events (workspace_id, user_id, entity_type, entity_id, action, metadata) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (workspace_id, user_id, entity_type, entity_id, action,
                 None if metadata is None else json.dumps(metadata, sort_keys=True)),
            )
            connection.commit()
        finally:
            connection.close()


__all__ = ["EngineeringApplication"]
