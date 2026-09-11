import tempfile
import unittest
from pathlib import Path

import db
import workspace_search
from workspace_application import WorkspaceApplication


class WorkspaceSearchTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        db.DB_PATH = Path(self.temp_dir.name) / "test.db"
        self.app = WorkspaceApplication(Path(self.temp_dir.name) / "storage")
        self.project_id = self.app.create_project("Search Project", "workspace search")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_search_finds_nested_names_and_note_content(self):
        folder = self.app.create_folder(self.project_id, "Design", None)
        nested = self.app.create_folder(self.project_id, "Hydraulics", folder)
        self.app.create_note(self.project_id, "Pressure Notes", "Darcy-Weisbach pressure loss", nested)
        self.app.create_note(self.project_id, "Unrelated", "different topic", None)

        matches = self.app.search_project(self.project_id, "pressure")
        self.assertEqual([(item.kind, item.name) for item in matches], [("note", "Pressure Notes")])

        name_matches = self.app.search_project_names(self.project_id, "hyd")
        self.assertEqual([(item.kind, item.name) for item in name_matches], [("folder", "Hydraulics")])

    def test_search_is_case_insensitive_and_rejects_empty_query(self):
        self.app.create_note(self.project_id, "Thermodynamics", "Ideal Gas Law")
        self.assertEqual(len(self.app.search_project(self.project_id, "  ideal   gas ")), 1)
        with self.assertRaises(ValueError):
            self.app.search_project(self.project_id, "   ")

    def test_non_recursive_search_only_covers_project_root(self):
        nested = self.app.create_folder(self.project_id, "Nested", None)
        self.app.create_note(self.project_id, "Inside", "target", nested)
        self.app.create_note(self.project_id, "Root", "target")
        self.assertEqual([item.name for item in self.app.search_project(self.project_id, "target", recursive=False)], ["Root"])


if __name__ == "__main__":
    unittest.main()
