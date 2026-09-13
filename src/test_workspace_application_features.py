import os
import tempfile
import unittest
from typing import cast

import db
from workspace_application import WorkspaceApplication


class TestWorkspaceApplicationFeatures(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_path = db.DATABASE_PATH
        db.DATABASE_PATH = os.path.join(self.temp_dir.name, "test.db")
        self.app = WorkspaceApplication(os.path.join(self.temp_dir.name, "storage"))
        self.project_id = self.app.create_project("Feature Project")

    def tearDown(self):
        db.DATABASE_PATH = self.original_path
        self.temp_dir.cleanup()

    def test_replace_file_updates_bytes_metadata_and_hash(self):
        file_id = self.app.create_file(self.project_id, "model.bin", b"old", "application/octet-stream")
        before = self.app.get_file(file_id); self.assertIsNotNone(before)
        if before is None: self.fail("file could not be retrieved")
        after = self.app.replace_file(file_id, b"new model", "application/octet-stream")
        self.assertEqual(self.app.read_file(file_id), b"new model")
        self.assertNotEqual(cast(dict[str, object], before)["sha256"], after["sha256"])
        self.assertEqual(after["size_bytes"], len(b"new model"))
        self.assertTrue(self.app.verify_file(file_id))

    def test_note_pin_export_and_properties(self):
        note_id = self.app.create_note(self.project_id, "Analysis", "Q = A*v")
        pinned = self.app.pin_note(note_id)
        self.assertTrue(pinned.metadata["pinned"])
        self.assertEqual(self.app.export_note(note_id), "Q = A*v")
        properties = self.app.get_item_properties("note", note_id)
        metadata = cast(dict[str, object], properties["metadata"])
        self.assertEqual(properties["content_length"], len("Q = A*v"))
        self.assertTrue(metadata["pinned"])

    def test_folder_properties_report_direct_children(self):
        folder = self.app.create_folder(self.project_id, "Calculations")
        self.app.create_note(self.project_id, "one", "1+1", folder)
        self.app.create_folder(self.project_id, "nested", folder)
        properties = self.app.get_item_properties("folder", folder)
        self.assertEqual(properties["child_count"], 2)


if __name__ == "__main__": unittest.main()
