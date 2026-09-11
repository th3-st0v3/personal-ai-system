import os
import tempfile
import unittest

import db
from workspace_application import WorkspaceApplication


class TestWorkspaceClipboard(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_path = db.DATABASE_PATH
        db.DATABASE_PATH = os.path.join(self.temp_dir.name, "test.db")
        self.app = WorkspaceApplication(os.path.join(self.temp_dir.name, "storage"))
        self.project_id = self.app.create_project("Clipboard Project")

    def tearDown(self):
        db.DATABASE_PATH = self.original_path
        self.temp_dir.cleanup()

    def test_duplicate_folder_copies_nested_note_and_file(self):
        root = self.app.create_folder(self.project_id, "Design")
        child = self.app.create_folder(self.project_id, "Inputs", root)
        note = self.app.create_note(self.project_id, "requirements", "pressure = 100 kPa", child)
        file_id = self.app.create_file(self.project_id, "data.txt", b"engineering data", "text/plain", child)

        duplicate = self.app.duplicate_item(self.project_id, "folder", root)
        children = self.app.list_children(self.project_id, duplicate)
        self.assertEqual([item.name for item in children], ["Inputs"])
        nested = children[0]
        nested_items = self.app.list_children(self.project_id, nested.id)
        self.assertEqual({item.name for item in nested_items}, {"data.txt", "requirements"})
        self.assertEqual(self.app.get_note(note).content, "pressure = 100 kPa")
        self.assertEqual(self.app.read_file(file_id), b"engineering data")

    def test_copy_and_paste_renames_conflicts(self):
        folder = self.app.create_folder(self.project_id, "Results")
        self.app.create_note(self.project_id, "report", "first", folder)
        clipboard = self.app.copy_selection(self.project_id, [("folder", folder)])
        pasted = self.app.paste_selection(self.project_id, None, clipboard)
        self.assertEqual(len(pasted), 1)
        self.assertEqual(self.app.get_folder(pasted[0])["name"], "Results (copy)")
        copied_items = self.app.list_children(self.project_id, pasted[0])
        self.assertEqual(copied_items[0].name, "report")
        self.assertEqual(copied_items[0].content, "first")

    def test_copy_rejects_other_project(self):
        other = self.app.create_project("Other")
        folder = self.app.create_folder(other, "Private")
        with self.assertRaises(ValueError):
            self.app.copy_selection(self.project_id, [("folder", folder)])


if __name__ == "__main__":
    unittest.main()
