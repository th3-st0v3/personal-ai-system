import io
import json
import os
import tempfile
import unittest

import db
from web_api import create_app
from workspace_application import WorkspaceApplication


class TestIngestionWebAPI(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original = db.DATABASE_PATH
        db.DATABASE_PATH = os.path.join(self.temp_dir.name, "web.db")
        self.workspace = WorkspaceApplication(os.path.join(self.temp_dir.name, "storage"))
        self.app = create_app(self.workspace)
        self.project_id = self.workspace.create_project("Evidence API")

    def tearDown(self):
        db.DATABASE_PATH = self.original
        self.temp_dir.cleanup()

    @staticmethod
    def decode(raw):
        return json.loads(raw.decode("utf-8"))

    def test_source_ingest_and_search(self):
        status, _, raw = self.app.request(
            "POST", f"/api/projects/{self.project_id}/sources",
            json.dumps({"title": "requirements.md", "content": "REQ-1 requires pressure above 5 MPa."}).encode(),
        )
        self.assertEqual(status, 201)
        source = self.decode(raw)
        self.assertEqual(source["title"], "requirements.md")

        status, _, raw = self.app.request(
            "GET", f"/api/projects/{self.project_id}/sources?q=5%20MPa&limit=5",
        )
        self.assertEqual(status, 200)
        hits = self.decode(raw)
        self.assertEqual(hits[0]["source"], "requirements.md")
        self.assertIn("5 MPa", hits[0]["content"])

    def test_source_does_not_cross_project_boundary(self):
        other = self.workspace.create_project("Other")
        status, _, _ = self.app.request(
            "POST", f"/api/projects/{other}/sources",
            json.dumps({"title": "a", "content": "private"}).encode(),
        )
        self.assertEqual(status, 201)
        status, _, raw = self.app.request(
            "GET", f"/api/projects/{self.project_id}/sources?q=private",
        )
        self.assertEqual(status, 200)
        self.assertEqual(self.decode(raw), [])


if __name__ == "__main__":
    unittest.main()
