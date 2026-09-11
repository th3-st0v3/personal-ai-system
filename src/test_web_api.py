import base64
import io
import json
import os
import tempfile
import unittest

import db
from web_api import WebApplication, create_app
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

    def request(self, method, path, payload=None, raw_body=None):
        body = raw_body if raw_body is not None else json.dumps(payload).encode() if payload is not None else b""
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
        self.assertEqual(manifest["workspace"]["kinds"], ["file", "folder", "note"])
        self.assertIn("last_modified_new_old", manifest["workspace"]["sort_options"])
        self.assertIn("new_note", manifest["workspace"]["context_actions"]["folder"])
        self.assertIn("copy", manifest["workspace"]["context_actions"]["folder"])
        self.assertIn("duplicate", manifest["workspace"]["context_actions"]["file"])
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
        gravity = next(parameter for parameter in detail["parameters"] if parameter["name"] == "gravity")
        self.assertFalse(gravity["required"])
        status, _, trace = self.request("POST", "/api/calculations/run", {"model_key": "hydrostatic_pressure", "inputs": {"density": 1000, "gravity": 9.81, "depth": 10}})
        self.assertEqual(status, 200)
        self.assertEqual(trace["result"], 98100.0)
        self.assertGreaterEqual(len(trace["steps"]), 6)
        self.assertIn("assumptions", trace)

    def test_workspace_items_search_and_breadcrumbs(self):
        root = self.workspace.create_folder(self.project_id, "Engineering")
        child = self.workspace.create_folder(self.project_id, "Hydraulics", root)
        self.workspace.create_note(self.project_id, "Pressure Note", "hydrostatic pressure", child)
        self.workspace.create_file(self.project_id, "data.txt", b"123", "text/plain", child)
        status, _, items = self.request("GET", f"/api/projects/{self.project_id}/items?folder_id={child}&sort=a_z")
        self.assertEqual(status, 200)
        self.assertEqual([item["name"] for item in items], ["data.txt", "Pressure Note"])
        status, _, matches = self.request("GET", f"/api/projects/{self.project_id}/search?q=hydrostatic")
        self.assertEqual(status, 200)
        self.assertEqual([item["name"] for item in matches], ["Pressure Note"])
        status, _, crumbs = self.request("GET", f"/api/projects/{self.project_id}/breadcrumbs?kind=folder&id={child}")
        self.assertEqual(status, 200)
        self.assertEqual([item["name"] for item in crumbs], ["Web Project", "Engineering", "Hydraulics"])

    def test_file_and_note_lifecycle_routes_are_project_scoped(self):
        root = self.workspace.create_folder(self.project_id, "Sources")
        data = b"hello beta"
        encoded = base64.b64encode(data).decode("ascii")
        status, _, payload = self.request("POST", f"/api/projects/{self.project_id}/files", {"name": "source.txt", "mime_type": "text/plain", "folder_id": root, "data_base64": encoded})
        self.assertEqual(status, 201)
        file_id = payload["id"]
        status, _, downloaded = self.request("GET", f"/api/projects/{self.project_id}/files?id={file_id}")
        self.assertEqual(status, 200)
        self.assertEqual(base64.b64decode(downloaded["data_base64"]), data)
        replacement = b"replacement"
        status, _, updated = self.request("PUT", f"/api/projects/{self.project_id}/files", {"id": file_id, "data_base64": base64.b64encode(replacement).decode("ascii"), "mime_type": "text/plain"})
        self.assertEqual(status, 200)
        self.assertEqual(updated["size_bytes"], len(replacement))
        self.assertEqual(self.workspace.read_file(file_id), replacement)
        note_id = self.workspace.create_note(self.project_id, "Draft", "old", root)
        status, _, note = self.request("PATCH", f"/api/projects/{self.project_id}/notes", {"id": note_id, "title": "Final", "content": "new"})
        self.assertEqual(status, 200)
        self.assertEqual((note["name"], note["content"]), ("Final", "new"))
        other_project = self.workspace.create_project("Other")
        self.assertEqual(self.request("GET", f"/api/projects/{other_project}/files?id={file_id}")[0], 400)
        self.assertEqual(self.request("PATCH", f"/api/projects/{other_project}/notes", {"id": note_id, "content": "leak"})[0], 400)
        self.assertEqual(self.workspace.read_file(file_id), replacement)
        self.assertEqual(self.workspace.get_note(note_id).content, "new")

    def test_copy_paste_and_duplicate_actions(self):
        source = self.workspace.create_folder(self.project_id, "Source")
        target = self.workspace.create_folder(self.project_id, "Target")
        note = self.workspace.create_note(self.project_id, "Read me", "copy me", source)
        file_id = self.workspace.create_file(self.project_id, "data.txt", b"123", "text/plain", source)
        status, _, payload = self.request("POST", f"/api/projects/{self.project_id}/copy", {"selection": [{"kind": "note", "id": note}, {"kind": "file", "id": file_id}]})
        self.assertEqual((status, payload), (200, {"copied": [{"kind": "note", "id": note}, {"kind": "file", "id": file_id}]}))
        status, _, payload = self.request("POST", f"/api/projects/{self.project_id}/paste", {"target_folder_id": target, "selection": [{"kind": "note", "id": note}, {"kind": "file", "id": file_id}]})
        self.assertEqual(status, 201)
        self.assertEqual(len(payload["created"]), 2)
        pasted = self.workspace.list_children(self.project_id, target)
        self.assertEqual({item.name for item in pasted}, {"Read me", "data.txt"})
        status, _, payload = self.request("POST", f"/api/projects/{self.project_id}/duplicate", {"kind": "note", "id": note})
        self.assertEqual(status, 201)
        self.assertEqual(self.workspace.get_note(payload["id"]).name, "Read me (copy)")
        copied_folder = self.workspace.create_folder(self.project_id, "Nested", source)
        self.workspace.create_note(self.project_id, "Nested note", "nested", copied_folder)
        status, _, payload = self.request("POST", f"/api/projects/{self.project_id}/duplicate", {"kind": "folder", "id": source})
        self.assertEqual(status, 201)
        duplicated_children = self.workspace.list_children(self.project_id, payload["id"])
        self.assertEqual({item.name for item in duplicated_children}, {"Read me", "Read me (copy)", "data.txt", "Nested"})
        nested_copy = next(item for item in duplicated_children if item.name == "Nested")
        self.assertEqual([item.name for item in self.workspace.list_children(self.project_id, nested_copy.id)], ["Nested note"])

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
        self.assertEqual(self.request("POST", "/api/projects/1/duplicate", {"kind": "unsupported", "id": 1})[0], 400)
        self.assertEqual(self.request("POST", "/api/projects/1/delete", {"selection": [{"kind": "unsupported", "id": 1}]})[0], 400)
        self.assertEqual(self.request("POST", "/api/calculations/run", raw_body=b"[]")[0], 400)
        self.assertEqual(self.request("POST", "/api/calculations/run", raw_body=b"x" * (WebApplication.MAX_REQUEST_BODY_BYTES + 1))[0], 400)
        self.assertEqual(self.request("POST", "/api/projects/1/files", {"name": "bad.txt", "data_base64": "not-base64"})[0], 400)
        self.assertEqual(self.request("GET", "/not-found")[0], 404)

    def test_wsgi_adapter_returns_json_and_rejects_oversized_content_length(self):
        captured = {}
        def start_response(status, headers): captured["status"], captured["headers"] = status, dict(headers)
        environ = {"REQUEST_METHOD": "GET", "PATH_INFO": "/api/health", "QUERY_STRING": "", "CONTENT_LENGTH": "0", "wsgi.input": io.BytesIO(b"")}
        body = b"".join(self.app(environ, start_response))
        self.assertEqual(captured["status"], "200 OK")
        self.assertEqual(json.loads(body), {"status": "ok"})
        self.assertIn("application/json", captured["headers"]["Content-Type"])
        environ["CONTENT_LENGTH"] = str(WebApplication.MAX_REQUEST_BODY_BYTES + 1)
        body = b"".join(self.app(environ, start_response))
        self.assertEqual(captured["status"], "413 Error")
        self.assertEqual(json.loads(body), {"error": "Request body too large."})


if __name__ == "__main__":
    unittest.main()