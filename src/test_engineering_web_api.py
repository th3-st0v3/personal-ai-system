import json
import os
import tempfile
import unittest
from typing import cast

import db
from engineering_web_api import create_engineering_app
from workspace_application import WorkspaceApplication


def as_int(value: object) -> int:
    if not isinstance(value, int): raise AssertionError(f"expected integer ID, got {value!r}")
    return value


class TestEngineeringWebApplication(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_db = db.DATABASE_PATH
        db.DATABASE_PATH = os.path.join(self.temp.name, "engineering.db")
        self.workspace = WorkspaceApplication(os.path.join(self.temp.name, "storage"))
        self.app = create_engineering_app()
        project_id = self.workspace.create_project("Engineering Project")
        if project_id is None:
            self.fail("project creation should return an ID")
        self.project_id = project_id

    def tearDown(self):
        db.DATABASE_PATH = self.original_db
        self.temp.cleanup()

    def request(self, method, path, payload=None):
        body = b"" if payload is None else json.dumps(payload).encode()
        status, _, raw = self.app.request(method, path, body)
        return status, json.loads(raw)

    def test_project_scoped_source_and_evidence_guards(self):
        other_project = as_int(self.workspace.create_project("Other"))
        source_id = as_int(self.app.engineering.create_source(self.project_id, "Private", "document"))
        with self.assertRaisesRegex(ValueError, "Source not found"):
            self.app._require_source(other_project, source_id)
        requirement_id = db.create_requirement(self.project_id, "Requirement")
        evidence_id = as_int(self.app.engineering.create_evidence(requirement_id, "Confirmed", "Verified", source="Private", description="Evidence"))
        with self.assertRaisesRegex(ValueError, "Evidence not found"):
            self.app._require_evidence(other_project, evidence_id)
        self.app._require_evidence(self.project_id, evidence_id)

    def test_requirement_source_evidence_and_decision_workflow(self):
        status, requirement = self.request("POST", f"/api/engineering/projects/{self.project_id}/requirements", {"description": "Pump must meet rated flow"})
        self.assertEqual(status, 201)
        requirement_id = as_int(requirement["id"])
        status, updated = self.request("PATCH", f"/api/engineering/projects/{self.project_id}/requirements/{requirement_id}", {"identifier": "REQ-001", "title": "Rated flow", "acceptance_criteria": "Within design envelope", "priority": "High", "status": "Unverified"})
        self.assertEqual(status, 200)
        self.assertEqual((updated["identifier"], updated["title"]), ("REQ-001", "Rated flow"))
        status, source = self.request("POST", f"/api/engineering/projects/{self.project_id}/sources", {"title": "Pump Datasheet", "source_type": "datasheet"})
        self.assertEqual(status, 201)
        source_id = as_int(source["id"])
        status, evidence = self.request("POST", f"/api/engineering/projects/{self.project_id}/requirements/{requirement_id}/evidence", {"result": "Rated flow confirmed", "supports_status": "Verified", "source": "Pump Datasheet", "source_id": source_id, "classification": "direct", "description": "Manufacturer specification"})
        self.assertEqual(status, 201)
        evidence_id = as_int(evidence["id"])
        status, history = self.request("GET", f"/api/engineering/projects/{self.project_id}/requirements/{requirement_id}/evidence")
        self.assertEqual(status, 200)
        history_items = cast(list[dict[str, object]], history)
        self.assertIn(evidence_id, {as_int(item["id"]) for item in history_items})
        status, result = self.request("POST", f"/api/engineering/projects/{self.project_id}/evidence/invalidate", {"id": evidence_id, "reason": "Superseded by revised datasheet"})
        self.assertEqual((status, result), (200, {"invalidated": True}))
        status, decision = self.request("POST", f"/api/engineering/projects/{self.project_id}/decisions", {"title": "Pump selection", "decision": "Use qualified pump", "requirement_id": requirement_id, "rationale": "Evidence supports rated flow"})
        self.assertEqual(status, 201)
        decision_id = as_int(decision["id"])
        status, decisions = self.request("GET", f"/api/engineering/projects/{self.project_id}/decisions")
        self.assertEqual(status, 200)
        decision_items = cast(list[dict[str, object]], decisions)
        self.assertEqual(as_int(decision_items[0]["id"]), decision_id)

    def test_requirement_history_is_project_scoped_and_tracks_verification_events(self):
        status, requirement = self.request(
            "POST",
            f"/api/engineering/projects/{self.project_id}/requirements",
            {"description": "Pressure must remain within the qualified envelope"},
        )
        self.assertEqual(status, 201)
        requirement_id = as_int(requirement["id"])

        status, source = self.request(
            "POST",
            f"/api/engineering/projects/{self.project_id}/sources",
            {"title": "Pressure datasheet", "source_type": "datasheet", "version": "2.0"},
        )
        self.assertEqual(status, 201)
        source_id = as_int(source["id"])

        status, evidence = self.request(
            "POST",
            f"/api/engineering/projects/{self.project_id}/requirements/{requirement_id}/evidence",
            {
                "result": "Measured pressure is within envelope",
                "supports_status": "Verified",
                "source": "Pressure datasheet",
                "source_id": source_id,
                "location": "Table 4",
                "evidence_type": "test_result",
            },
        )
        self.assertEqual(status, 201)
        evidence_id = as_int(evidence["id"])

        status, decision = self.request(
            "POST",
            f"/api/engineering/projects/{self.project_id}/decisions",
            {
                "title": "Retain qualified pressure limit",
                "decision": "Use the qualified pressure limit",
                "requirement_id": requirement_id,
                "rationale": "Measured evidence supports the limit.",
            },
        )
        self.assertEqual(status, 201)
        decision_id = as_int(decision["id"])

        status, result = self.request(
            "POST",
            f"/api/engineering/projects/{self.project_id}/evidence/invalidate",
            {"id": evidence_id, "reason": "Superseded by revised measurement"},
        )
        self.assertEqual((status, result), (200, {"invalidated": True}))

        status, history = self.request(
            "GET",
            f"/api/engineering/projects/{self.project_id}/requirements/{requirement_id}/history",
        )
        self.assertEqual(status, 200)
        events = cast(list[dict[str, object]], history)
        event_types = {str(item["event_type"]) for item in events}
        self.assertIn("requirement_record", event_types)
        self.assertIn("evidence_recorded", event_types)
        self.assertIn("decision_recorded", event_types)
        self.assertIn("evidence_invalidated", event_types)
        evidence_event = next(item for item in events if item["event_type"] == "evidence_recorded")
        self.assertEqual(as_int(evidence_event["entity_id"]), evidence_id)
        self.assertEqual(as_int(cast(dict[str, object], evidence_event["source"])["id"]), source_id)
        decision_event = next(item for item in events if item["event_type"] == "decision_recorded")
        self.assertEqual(as_int(decision_event["entity_id"]), decision_id)

        status, other = self.request(
            "GET",
            f"/api/engineering/projects/{self.project_id}/requirements/999999/history",
        )
        self.assertEqual(status, 400)
        self.assertIn("Requirement not found", str(other["error"]))

    def test_cross_project_requirement_and_source_access_is_rejected(self):
        other_project = as_int(self.workspace.create_project("Other"))
        status, created = self.request("POST", f"/api/engineering/projects/{self.project_id}/requirements", {"description": "Private"})
        self.assertEqual(status, 201)
        private_requirement = as_int(created["id"])
        self.assertEqual(self.request("PATCH", f"/api/engineering/projects/{other_project}/requirements/{private_requirement}", {"title": "Leak"})[0], 400)
        status, source = self.request("POST", f"/api/engineering/projects/{self.project_id}/sources", {"title": "Private", "source_type": "document"})
        self.assertEqual(status, 201)
        source_id = as_int(source["id"])
        status, other_requirement = self.request("POST", f"/api/engineering/projects/{other_project}/requirements", {"description": "Other"})
        self.assertEqual(status, 201)
        other_requirement_id = as_int(other_requirement["id"])
        self.assertEqual(self.request("POST", f"/api/engineering/projects/{other_project}/requirements/{other_requirement_id}/evidence", {"result": "leak", "supports_status": "Verified", "source": "Private", "source_id": source_id, "description": "cross-project attempt"})[0], 400)

    def test_invalid_routes_and_bodies_are_client_errors(self):
        self.assertEqual(self.request("GET", "/api/engineering/projects/not-an-id/requirements")[0], 400)
        self.assertEqual(self.request("GET", "/api/engineering/projects/9999/requirements")[0], 400)
        self.assertEqual(self.request("POST", f"/api/engineering/projects/{self.project_id}/requirements", {"bogus": 1})[0], 400)
        self.assertEqual(self.request("POST", f"/api/engineering/projects/{self.project_id}/requirements/9999/evidence", {"result": "x", "supports_status": "Verified"})[0], 400)


if __name__ == "__main__": unittest.main()
