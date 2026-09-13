import json
import os
import tempfile
import unittest

import db
from engineering_web_api import create_engineering_app
from workspace_application import WorkspaceApplication


class TestEngineeringIngestionAPI(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original = db.DATABASE_PATH
        db.DATABASE_PATH = os.path.join(self.temp.name, "test.db")
        self.workspace = WorkspaceApplication(os.path.join(self.temp.name, "storage"))
        self.project_id = self.workspace.create_project("Ingestion")
        self.app = create_engineering_app()

    def tearDown(self):
        db.DATABASE_PATH = self.original
        self.temp.cleanup()

    @staticmethod
    def decode(raw):
        return json.loads(raw.decode("utf-8"))

    def test_ingest_and_search(self):
        status, _, raw = self.app.request(
            "POST", f"/api/engineering/projects/{self.project_id}/sources/ingest",
            json.dumps({"title": "notes.md", "content": "Torque limit is 10 N m."}).encode(),
        )
        self.assertEqual(status, 201)
        self.assertEqual(self.decode(raw)["chunks"][0]["index"], 0)

        status, _, raw = self.app.request(
            "GET", f"/api/engineering/projects/{self.project_id}/sources/search?q=Torque",
        )
        self.assertEqual(status, 200)
        self.assertEqual(self.decode(raw)[0]["source"], "notes.md")


if __name__ == "__main__":
    unittest.main()
