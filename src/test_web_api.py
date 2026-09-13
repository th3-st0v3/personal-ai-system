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

    def request(self, method, path, payload=None, raw_body=None, environ=None):
        body = raw_body if raw_body is not None else json.dumps(payload).encode() if payload is not None else b""
        status, headers, raw = self.app.request(method, path, body, environ=environ)
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
        self.assertEqual(manifest["api_version"], 3)
        self.assertEqual(manifest["workspace"]["kinds"], ["folder", "note", "file"])
        self.assertIn("none", manifest["workspace"]["sort_options"])
        self.assertIn("last_modified_new_old", manifest["workspace"]["sort_options"])
        self.assertIn("new_note", manifest["workspace"]["context_actions"]["folder"])
        self.assertIn("copy", manifest["workspace"]["context_actions"]["folder"])
        self.assertIn("duplicate", manifest["workspace"]["context_actions"]["file"])
        self.assertIn("archive", manifest["workspace"]["multi_selection_actions"])
        self.assertIn("invalidate", manifest["workspace"]["multi_selection_actions"])
        self.assertIn("delete", manifest["workspace"]["multi_selection_actions"])
        self.assertGreaterEqual(manifest["calculations"]["count"], 28)
        self.assertGreaterEqual(len(manifest["simulations"]), 2)
        self.assertIn("Education", manifest["navigation"])

    def test_auth_signup_login_and_me_are_optional(self):
        status, headers, payload = self.request("POST", "/api/auth/signup", {"email": "riley@example.com", "password": "safe-pass-123", "display_name": "Riley"})
        self.assertEqual(status, 201)
        self.assertEqual(payload["user"]["display_name"], "Riley")
        cookie = headers["Set-Cookie"].split(";", 1)[0]
        status, _, me = self.request("GET", "/api/auth/me", environ={"HTTP_COOKIE": cookie})
        self.assertEqual(status, 200)
        self.assertEqual(me["user"]["email"], "riley@example.com")
        status, _, payload = self.request("POST", "/api/auth/logout", environ={"HTTP_COOKIE": cookie})
        self.assertEqual((status, payload), (200, {"logged_out": True}))
        status, _, me = self.request("GET", "/api/auth/me", environ={"HTTP_COOKIE": cookie})
        self.assertIsNone(me["user"])
        status, _, _ = self.request("POST", "/api/auth/login", {"email": "riley@example.com", "password": "safe-pass-123"})
        self.assertEqual(status, 200)

    def test_project_metadata_and_chat_are_persistent(self):
        status, _, project = self.request("PATCH", f"/api/projects/{self.project_id}", {"name": "Updated Project", "description": "Project description"})
        self.assertEqual(status, 200)
        self.assertEqual((project["name"], project["description"]), ("Updated Project", "Project description"))
        status, _, created = self.request("POST", "/api/chats", {"project_id": self.project_id})
        self.assertEqual(status, 201)
        chat_id = created["id"]
        status, _, chat = self.request("POST", f"/api/chats/{chat_id}/messages", {"content": "Explain a simple pressure model.", "mode": "local"})
        self.assertEqual(status, 200)
        self.assertEqual(chat["messages"][0]["role"], "user")
        self.assertEqual(chat["messages"][-1]["role"], "assistant")
        self.assertIn("local mode", chat["messages"][-1]["content"])

    def test_simulation_endpoint_returns_traceable_result(self):
        status, _, result = self.request("POST", "/api/simulations/run", {"simulation_key": "heat_conduction", "inputs": {"conductivity": 10, "area": 2, "hot_temperature": 400, "cold_temperature": 300, "thickness": 0.5}})
        self.assertEqual(status, 200)
        self.assertEqual(result["outputs"]["heat_rate"], 4000.0)
        self.assertTrue(result["steps"])
        self.assertTrue(result["assumptions"])
        self.assertTrue(result["limitations"])

    def test_calculation_catalog_and_trace(self):
        status, _, catalog = self.request("GET", "/api/calculations/catalog?category=Reservoir%20Engineering")
        self.assertEqual(status, 200)
        hydrostatic = next(item for item in catalog if item["key"] == "hydrostatic_pressure")
        self.assertIn("Drilling Engineering", hydrostatic["categories"])
        status, _, detail = self.request("GET", "/api/calculations/hydrostatic_pressure")
        self.assertEqual(status, 200)
        self.assertEqual(detail["parameters"][0]["name"], "density")
        status, _, pressure_head_detail = self.request("GET", "/api/calculations/pressure_head")
        self.assertEqual(status, 200)
        gravity = next(parameter for parameter in pressure_head_detail["parameters"] if parameter["name"] == "gravity")
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
        duplicated_note = self.workspace.get_note(payload["id"])
        if duplicated_note is None:
            self.fail("duplicated note should exist")
        self.assertEqual(duplicated_note.name, "Read me (copy)")
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
        moved_note = self.workspace.get_note(note)
        if moved_note is None:
            self.fail("moved note should exist")
        self.assertEqual(moved_note.parent_id, target)
        status, _, payload = self.request("POST", f"/api/projects/{self.project_id}/rename", {"kind": "note", "id": note, "name": "Renamed"})
        self.assertEqual((status, payload), (200, {"renamed": True}))
        renamed_note = self.workspace.get_note(note)
        if renamed_note is None:
            self.fail("renamed note should exist")
        self.assertEqual(renamed_note.name, "Renamed")
        status, _, props = self.request("GET", f"/api/projects/{self.project_id}/properties?kind=note&id={note}")
        self.assertEqual(status, 200)
        self.assertEqual(props["name"], "Renamed")
        status, _, payload = self.request("POST", f"/api/projects/{self.project_id}/delete", {"selection": [{"kind": "note", "id": note}]})
        self.assertEqual((status, payload), (200, {"deleted": 1}))
        self.assertIsNone(self.workspace.get_note(note))

    def test_file_and_note_lifecycle_routes_are_project_scoped(self):
        file_id = self.workspace.create_file(self.project_id, "data.txt", b"v1", "text/plain")
        status, _, props = self.request("GET", f"/api/projects/{self.project_id}/files?id={file_id}")
        self.assertEqual(status, 200)
        self.assertEqual(props["size_bytes"], 2)
        self.assertNotIn("sha256", props)
        status, _, payload = self.request("PUT", f"/api/projects/{self.project_id}/files", {"id": file_id, "data_base64": "djI=", "mime_type": "text/plain"})
        self.assertEqual(status, 200)
        self.assertEqual(payload["size_bytes"], 2)
        note_id = self.workspace.create_note(self.project_id, "Editable", "before", metadata={"description": "before description"})
        status, _, note = self.request("PATCH", f"/api/projects/{self.project_id}/notes", {"id": note_id, "content": "after", "metadata": {"description": "after description"}})
        self.assertEqual(status, 200)
        self.assertEqual(note["content"], "after")
        self.assertEqual(note["metadata"]["description"], "after description")
        other = self.workspace.create_project("Other")
        self.assertEqual(self.request("GET", f"/api/projects/{other}/files?id={file_id}")[0], 400)
        self.assertEqual(self.request("GET", f"/api/projects/{other}/notes?id={note_id}")[0], 400)

    def test_bad_requests_are_client_errors(self):
        self.assertEqual(self.request("GET", "/api/projects/not-an-id")[0], 400)
        self.assertEqual(self.request("GET", "/api/calculations/catalog?category=missing")[0], 400)
        self.assertEqual(self.request("POST", "/api/calculations/run", {"model_key": "missing", "inputs": {}})[0], 400)
        self.assertEqual(self.request("POST", "/api/projects/1/duplicate", {"kind": "unsupported", "id": 1})[0], 400)
        self.assertEqual(self.request("POST", "/api/projects/1/delete", {"selection": [{"kind": "unsupported", "id": 1}]})[0], 400)
        self.assertEqual(self.request("POST", "/api/calculations/run", raw_body=b"[]")[0], 400)
        self.assertEqual(self.request("POST", "/api/calculations/run", raw_body=b"x" * (WebApplication.MAX_REQUEST_BODY_BYTES + 1))[0], 413)
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


if __name__ == "__main__": unittest.main()
