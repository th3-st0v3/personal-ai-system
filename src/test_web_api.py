import io
import json
import os
import tempfile
import unittest

import db
from web_api import create_app
from workspace_application import WorkspaceApplication


class TestWebApplication(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_db = db.DATABASE_PATH
        db.DATABASE_PATH = os.path.join(self.temp.name, "web.db")
        self.workspace = WorkspaceApplication(os.path.join(self.temp.name, "storage"))
        self.app = create_app(self.workspace)
        self.project_id = self.workspace.create_project("Web Project")

    def tearDown(self):
        db.DATABASE_PATH = self.original_db
        self.temp.cleanup()

    def request(self, method, path, payload=None):
        body = json.dumps(payload).encode() if payload is not None else b""
        status, headers, raw = self.app.request(method, path, body)
        return status, dict(headers), json.loads(raw)

    def test_health_and_projects(self):
        self.assertEqual(self.request("GET", "/api/health")[2], {"status": "ok"})
        status, _, payload = self.request("GET", "/api/projects")
        self.assertEqual(status, 200)
        self.assertEqual(payload[0]["id"], self.project_id)

    def test_create_project(self):
        status, _, payload = self.request("POST", "/api/projects", {"name": "Created", "description": "api"})
        self.assertEqual(status, 201)
        self.assertEqual(payload["id"], 2)

    def test_manifest_matches_backend_capabilities(self):
        status, _, manifest = self.request("GET", "/api/manifest")
        self.assertEqual(status, 200)
        self.assertEqual(manifest["api_version"], 1)
        self.assertEqual(manifest["workspace"]["kinds"], ["folder", "note", "file"])
        self.assertIn("last_modified_new_old", manifest["workspace"]["sort_options"])
        self.assertIn("new_note", manifest["workspace"]["context_actions"]["folder"])
        self.assertIn("delete", manifest["workspace"]["multi_selection_actions"])
        self.assertGreaterEqual(manifest["calculations"]["count"], 28)

    def test_calculation_catalog_and_trace(self):
        status, _, catalog = self.request("GET", "/api/calculations/catalog?category=Reservoir%20Engineering")
        self.assertEqual(status, 200)
        hydrostatic = next(item for item in catalog if item["key"] == "hydrostatic_pressure")
        self.assertIn("Drilling Engineering", hydrostatic["categories"])

        status, _, detail = self.request("GET", "/api/calculations/hydrostatic_pressure")
        self.assertEqual(status, 200)
        self.assertEqual(detail["parameters"][0]["name"], "density")

        status, _, trace = self.request("POST", "/api/calculations/run", {"model_key": "hydrostatic_pressure", "inputs": {"density": 1000, "gravity": 9.81, "depth": 10}})
        self.assertEqual(status, 200)
        self.assertEqual(trace["result"], 98100.0)
        self.assertGreaterEqual(len(trace["steps"]), 6)
        self.assertIn("assumptions", trace)

    def test_workspace_items_and_search(self):
        folder = self.workspace.create_folder(self.project_id, "Engineering")
        self.workspace.create_note(self.project_id, "Pressure Note", "hydrostatic pressure", folder)
        self.workspace.create_file(self.project_id, "data.txt", b"123", "text/plain", folder)
        status, _, items = self.request("GET", f"/api/projects/{self.project_id}/items?folder_id={folder}&sort=a_z")
        self.assertEqual(status, 200)
        self.assertEqual([item["name"] for item in items], ["data.txt", "Pressure Note"])

        status, _, matches = self.request("GET", f"/api/projects/{self.project_id}/search?q=hydrostatic")
        self.assertEqual(status, 200)
        self.assertEqual([item["name"] for item in matches], ["Pressure Note"])

    def test_workspace_actions_are_exposed(self):
        source = self.workspace.create_folder(self.project_id, "Source")
        target = self.workspace.create_folder(self.project_id, "Target")
        note = self.workspace.create_note(self.project_id, "Move me", "content", source)
        status, _, payload = self.request("POST", f"/api/projects/{self.project_id}/move", {"kind": "note", "id": note, "target_folder_id": target})
        self.assertEqual((status, payload), (200, {"moved": True}))
        self.assertEqual(self.workspace.get_note(note).parent_id, target)

        status, _, payload = self.request("POST", f"/api/projects/{self.project_id}/rename", {"kind": "note", "id": note, "name": "Renamed"})
        self.assertEqual((status, payload), (200, {"renamed": True}))
        self.assertEqual(self.workspace.get_note(note).name, "Renamed")

        status, _, props = self.request("GET", f"/api/projects/{self.project_id}/properties?kind=note&id={note}")
        self.assertEqual(status, 200)
        self.assertEqual(props["name"], "Renamed")

        status, _, payload = self.request("POST", f"/api/projects/{self.project_id}/delete", {"selection": [{"kind": "note", "id": note}]})
        self.assertEqual((status, payload), (200, {"deleted": 1}))
        self.assertIsNone(self.workspace.get_note(note))

    def test_bad_requests_are_client_errors(self):
        self.assertEqual(self.request("GET", "/api/projects/not-an-id")[0], 400)
        self.assertEqual(self.request("GET", "/api/calculations/catalog?category=missing")[0], 400)
        self.assertEqual(self.request("POST", "/api/calculations/run", {"model_key": "missing", "inputs": {}})[0], 400)
        self.assertEqual(self.request("GET", "/not-found")[0], 404)

    def test_wsgi_adapter_returns_json(self):
        captured = {}

        def start_response(status, headers):
            captured["status"] = status
            captured["headers"] = dict(headers)

        environ = {
            "REQUEST_METHOD": "GET",
            "PATH_INFO": "/api/health",
            "QUERY_STRING": "",
            "CONTENT_LENGTH": "0",
            "wsgi.input": io.BytesIO(b""),
        }
        body = b"".join(self.app(environ, start_response))
        self.assertEqual(captured["status"], "200 OK")
        self.assertEqual(json.loads(body), {"status": "ok"})
        self.assertIn("application/json", captured["headers"]["Content-Type"])


if __name__ == "__main__":
    unittest.main()
