import os
import sqlite3
import tempfile
import unittest
from typing import cast

import db
from engineering_application import EngineeringApplication


class TestEngineeringApplication(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_path = db.DATABASE_PATH
        db.DATABASE_PATH = os.path.join(self.temp_dir.name, "test.db")
        connection = sqlite3.connect(db.DATABASE_PATH)
        connection.execute("PRAGMA foreign_keys = ON")
        db.initialize_database(connection)
        connection.close()
        self.app = EngineeringApplication()
        project_id = self.app.create_project("Reservoir Study", "Test project")
        if project_id is None:
            self.fail("project creation should return an ID")
        self.project_id = project_id

    def tearDown(self):
        db.DATABASE_PATH = self.original_path
        self.temp_dir.cleanup()

    def test_workspace_and_membership(self):
        workspace_id = self.app.create_workspace("Engineering")
        user_id = self.app.create_user("Test Engineer", "engineer@example.com")
        self.app.add_workspace_member(workspace_id, user_id, "owner")
        members = self.app.list_workspace_members(workspace_id)
        self.assertEqual([member["id"] for member in members], [user_id])
        self.assertEqual(members[0]["email"], "engineer@example.com")

    def test_project_assignment_and_rich_requirement_update(self):
        workspace_id = self.app.create_workspace("Engineering")
        user_id = self.app.create_user("Test Engineer")
        self.app.assign_project(self.project_id, workspace_id, user_id)
        requirement_id = db.create_requirement(self.project_id, "Maintain pressure")
        self.app.update_requirement(requirement_id, identifier="REQ-001", title="Pressure requirement", acceptance_criteria="Pressure remains above threshold", priority="High", status="Verified")
        project = self.app.get_project(self.project_id)
        if project is None:
            self.fail("project should exist after creation")
        requirement = self.app.list_requirements(self.project_id)[0]
        identifier = requirement.get("identifier")
        status = requirement.get("status")
        priority = requirement.get("priority")
        if not isinstance(identifier, str) or not isinstance(status, str) or not isinstance(priority, str):
            self.fail("updated requirement should contain identifier, status, and priority")
        self.assertEqual(project["workspace_id"], workspace_id)
        self.assertEqual(project["owner_id"], user_id)
        self.assertEqual(identifier, "REQ-001")
        self.assertEqual(status, "Verified")
        self.assertEqual(priority, "High")

    def test_source_evidence_and_invalidation(self):
        requirement_id = db.create_requirement(self.project_id, "Support the design")
        source_id = self.app.create_source(self.project_id, "Reservoir report", "report", author="Engineer", publisher="Operator", version="1.2")
        evidence_id = self.app.create_evidence(requirement_id, "Pressure supports design", "Verified", source="Reservoir report", source_id=source_id, classification="analysis", description="Pressure data supports the selected design.")
        evidence = self.app.get_evidence(evidence_id)
        if evidence is None:
            self.fail("evidence should exist after creation")
        evidence_record = cast(dict[str, object], evidence)
        self.assertEqual(evidence_record["source_id"], source_id)
        self.assertEqual(evidence_record["classification"], "analysis")
        self.app.invalidate_evidence(evidence_id, "Superseded by revised report")
        evidence = self.app.get_evidence(evidence_id)
        if evidence is None:
            self.fail("invalidated evidence should remain retrievable")
        evidence_record = cast(dict[str, object], evidence)
        self.assertEqual(evidence_record["lifecycle_status"], "Invalidated")
        self.assertEqual(evidence_record["invalidation_reason"], "Superseded by revised report")

    def test_decision_and_audit_event(self):
        decision_id = self.app.create_decision(self.project_id, "Select completion method", "Use completion method A", rationale="Lower expected operating risk")
        audit_id = self.app.record_audit_event("decision", decision_id, "created", metadata={"reason": "initial design selection"})
        decision = self.app.list_decisions(self.project_id)[0]
        self.assertEqual(decision["id"], decision_id)
        self.assertEqual(decision["status"], "Active")
        connection = db.get_connection()
        try:
            row = connection.execute("SELECT entity_type, entity_id, action, metadata FROM audit_events WHERE id = ?", (audit_id,)).fetchone()
        finally:
            connection.close()
        self.assertIsNotNone(row)
        audit_row = cast(tuple[object, object, object, object], row)
        self.assertEqual(audit_row[0:3], ("decision", decision_id, "created"))
        self.assertEqual(audit_row[3], '{"reason": "initial design selection"}')

    def test_invalid_updates_are_rejected(self):
        with self.assertRaises(ValueError): self.app.create_workspace("   ")
        with self.assertRaises(ValueError): self.app.update_requirement(99999, status="Unknown")
        with self.assertRaises(ValueError): self.app.create_decision(self.project_id, "", "Decision")
        with self.assertRaises(ValueError): self.app.invalidate_evidence(99999, "reason")


if __name__ == "__main__":
    unittest.main()
