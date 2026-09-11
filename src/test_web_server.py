import io
import json
import os
import tempfile
import unittest

import db
from web_api import create_app
from web_server import create_site_app
from workspace_application import WorkspaceApplication


class TestSiteApplication(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_db = db.DATABASE_PATH
        db.DATABASE_PATH = os.path.join(self.temp.name, "site.db")
        self.workspace = WorkspaceApplication(os.path.join(self.temp.name, "storage"))
        self.api = create_app(self.workspace)
        self.project_id = self.workspace.create_project("Site Project")
        self.site = create_site_app(self.api, os.path.join(os.path.dirname(__file__), "..", "web"))

    def tearDown(self):
        db.DATABASE_PATH = self.original_db
        self.temp.cleanup()

    def call(self, path):
        captured = {}
        def start_response(status, headers): captured["status"], captured["headers"] = status, dict(headers)
        body = b"".join(self.site({"REQUEST_METHOD": "GET", "PATH_INFO": path, "QUERY_STRING": "", "CONTENT_LENGTH": "0", "wsgi.input": io.BytesIO(b"")}, start_response))
        return captured, body

    def test_serves_interactive_client_assets(self):
        for path, content_type in (("/", "text/html"), ("/app.js", "text/javascript"), ("/keyboard.js", "text/javascript"), ("/workspace-root.js", "text/javascript"), ("/workspace-interactions.js", "text/javascript"), ("/engineering.js", "text/javascript"), ("/styles.css", "text/css")):
            response, body = self.call(path)
            self.assertEqual(response["status"], "200 OK")
            self.assertIn(content_type, response["headers"]["Content-Type"])
            self.assertGreater(len(body), 100)
        _, index = self.call("/")
        text = index.decode()
        for asset in ("/keyboard.js", "/workspace-root.js", "/workspace-interactions.js", "/engineering.js"):
            self.assertIn(asset, text)

    def test_delegates_api_routes(self):
        response, body = self.call("/api/health")
        self.assertEqual(response["status"], "200 OK")
        self.assertEqual(json.loads(body), {"status": "ok"})

    def test_delegates_engineering_routes(self):
        response, body = self.call(f"/api/engineering/projects/{self.project_id}/requirements")
        self.assertEqual(response["status"], "200 OK")
        self.assertEqual(json.loads(body), [])

    def test_rejects_path_traversal(self):
        response, _ = self.call("/../README.md")
        self.assertEqual(response["status"], "404 Error")


if __name__ == "__main__":
    unittest.main()
