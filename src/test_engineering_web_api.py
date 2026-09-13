import json
import os
import tempfile
import unittest

import db
from engineering_web_api import create_engineering_app
from workspace_application import WorkspaceApplication


class TestEngineeringWebApplication(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_db = db.DATABASE_PATH
        db.DATABASE_PATH = os.path.join(self.temp.name, "engineering.db")
        self.workspace = WorkspaceApplication(os.path.join(self.temp.name, "storage"))
        self.app = create_engineering_app()
        self.project_id = self.workspace.create_project("Engineering Project")

    def tearDown(self):
        db.DATABASE_PATH = self.original_db
        self.temp.cleanup()

    def request(self, method, path, payload=None):
        body = b"" if payload is None else json.dumps(payload).encode()
        status, _, raw = self.app.request(method, path, body)
        return status, json.loads(raw)

    def test_project_scoped_source_and_evidence_guards(self):
        other_project = self.workspace.create_project("Other")
        source_id = self.app.engineering.create_source(self.project_id, "Private", "document")
        with self.assertRaisesRegex(ValueError, "Source not found"):
            self.app._require_source(other_project, source_id)
        requirement_id = db.create_requirement(self.project_id, "Requirement")
        evidence_id = self.app.engineering.create_evidence(requirement_id, "Confirmed", "Verified", source="Private", description="Evidence")
        with self.assertRaisesRegex(ValueError, "Evidence not found"):
            self.app._require_evidence(other_project, evidence_id)
        self.app._require_evidence(self.project_id, evidence_id)

    def test_requirement_source_evidence_and_decision_workflow(self):
        status, requirement = self.request("POST", f"/api/engineering/projects/{self.project_id}/requirements", {"description": "Pump must meet rated flow"})
        self.assertEqual(status, 201)
        requirement_id = requirement["id"]
        status, updated = self.request("PATCH", f"/api/engineering/projects/{self.project_id}/requirements/{requirement_id}", {"identifier": "REQ-001", "title": "Rated flow", "acceptance_criteria": "Within design envelope", "priority": "High", "status": "Unverified"})
        self.assertEqual(status, 200)
        self.assertEqual((updated["identifier"], updated["title"]), ("REQ-001", "Rated flow"))
        status, source = self.request("POST", f"/api/engineering/projects/{self.project_id}/sources", {"title": "Pump Datasheet", "source_type": "datasheet"})
        self.assertEqual(status, 201)
        source_id = source["id"]
        status, evidence = self.request("POST", f"/api/engineering/projects/{self.project_id}/requirements/{requirement_id}/evidence", {"result": "Rated flow confirmed", "supports_status": "Verified", "source": "Pump Datasheet", "source_id": source_id, "classification": "direct", "description": "Manufacturer specification"})
        self.assertEqual(status, 201)
        evidence_id = evidence["id"]
        status, history = self.request("GET", f"/api/engineering/projects/{self.project_id}/requirements/{requirement_id}/evidence")
        self.assertEqual(status, 200)
        self.assertIn(evidence_id, {item["id"] for item in history})
        status, result = self.request("POST", f"/api/engineering/projects/{self.project_id}/evidence/invalidate", {"id": evidence_id, "reason": "Superseded by revised datasheet"})
        self.assertEqual((status, result), (200, {"invalidated": True}))
        status, decision = self.request("POST", f"/api/engineering/projects/{self.project_id}/decisions", {"title": "Pump selection", "decision": "Use qualified pump", "requirement_id": requirement_id, "rationale": "Evidence supports rated flow"})
        self.assertEqual(status, 201)
        status, decisions = self.request("GET", f"/api/engineering/projects/{self.project_id}/decisions")
        self.assertEqual(status, 200)
        self.assertEqual(decisions[0]["id"], decision["id"])

    def test_cross_project_requirement_and_source_access_is_rejected(self):
        other_project = self.workspace.create_project("Other")
        status, created = self.request("POST", f"/api/engineering/projects/{self.project_id}/requirements", {"description": "Private"})
        self.assertEqual(status, 201)
        private_requirement = created["id"]
        self.assertEqual(self.request("PATCH", f"/api/engineering/projects/{other_project}/requirements/{private_requirement}", {"title": "Leak"})[0], 400)
        status, source = self.request("POST", f"/api/engineering/projects/{self.project_id}/sources", {"title": "Private", "source_type": "document"})
        self.assertEqual(status, 201)
        source_id = source["id"]
        status, other_requirement = self.request("POST", f"/api/engineering/projects/{other_project}/requirements", {"description": "Other"})
        self.assertEqual(status, 201)
        other_requirement_id = other_requirement["id"]
        self.assertEqual(self.request("POST", f"/api/engineering/projects/{other_project}/requirements/{other_requirement_id}/evidence", {"result": "leak", "supports_status": "Verified", "source": "Private", "source_id": source_id, "description": "cross-project attempt"})[0], 400)

    def test_invalid_routes_and_bodies_are_client_errors(self):
        self.assertEqual(self.request("GET", "/api/engineering/projects/not-an-id/requirements")[0], 400)
        self.assertEqual(self.request("GET", "/api/engineering/projects/9999/requirements")[0], 400)
        self.assertEqual(self.request("POST", f"/api/engineering/projects/{self.project_id}/requirements", {"bogus": 1})[0], 400)
        self.assertEqual(self.request("POST", f"/api/engineering/projects/{self.project_id}/requirements/9999/evidence", {"result": "x", "supports_status": "Verified"})[0], 400)


if __name__ == "__main__":
    unittest.main()
