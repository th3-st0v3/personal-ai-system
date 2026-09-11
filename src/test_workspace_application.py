import hashlib
import os
import tempfile
import unittest

import db
import file_storage
from workspace_application import WorkspaceApplication


class TestWorkspaceApplication(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_path = db.DATABASE_PATH
        db.DATABASE_PATH = os.path.join(self.temp_dir.name, "test.db")
        self.app = WorkspaceApplication(self.temp_dir.name)
        self.project_id = self.app.create_project("Application Test")

    def tearDown(self):
        db.DATABASE_PATH = self.original_path
        self.temp_dir.cleanup()

    def test_project_list_returns_named_records(self):
        projects = self.app.list_projects()
        self.assertEqual(projects[0]["id"], self.project_id)
        self.assertEqual(projects[0]["name"], "Application Test")

    def test_folder_operations_return_application_records(self):
        root_id = self.app.create_folder(self.project_id, "References")
        child_id = self.app.create_folder(self.project_id, "Papers", root_id)

        root = self.app.get_folder(root_id)
        children = self.app.list_folders(self.project_id, root_id)

        self.assertIsNotNone(root)
        if root is None:
            self.fail("folder could not be retrieved")
        self.assertEqual(root["name"], "References")
        self.assertEqual(root["parent_folder_id"], None)
        self.assertEqual(children[0]["id"], child_id)
        self.assertEqual(children[0]["parent_folder_id"], root_id)

    def test_folder_lifecycle_and_move_use_application_boundary(self):
        first_id = self.app.create_folder(self.project_id, "First")
        second_id = self.app.create_folder(self.project_id, "Second")

        self.app.rename_folder(first_id, "Renamed")
        self.app.move_folder(first_id, second_id)
        self.app.set_folder_lifecycle(first_id, "Archived")

        folder = self.app.get_folder(first_id)
        self.assertIsNotNone(folder)
        if folder is None:
            self.fail("folder could not be retrieved")
        self.assertEqual(folder["name"], "Renamed")
        self.assertEqual(folder["parent_folder_id"], second_id)
        self.assertEqual(folder["lifecycle_status"], "Archived")

    def test_file_creation_exposes_metadata_but_preserves_storage_boundary(self):
        payload = b"engineering evidence"
        file_id = self.app.create_file(
            self.project_id,
            "evidence.txt",
            payload,
            "text/plain",
        )

        record = self.app.get_file(file_id)
        self.assertIsNotNone(record)
        if record is None:
            self.fail("file could not be retrieved")
        self.assertEqual(record["name"], "evidence.txt")
        self.assertEqual(record["size_bytes"], len(payload))
        self.assertEqual(record["sha256"], hashlib.sha256(payload).hexdigest())
        self.assertTrue(record["storage_key"].startswith("files/"))

    def test_file_read_and_integrity_verification(self):
        payload = b"verified content"
        file_id = self.app.create_file(self.project_id, "data.txt", payload)

        self.assertEqual(self.app.read_file(file_id), payload)
        self.assertTrue(self.app.verify_file(file_id))

    def test_file_rename_and_move_do_not_change_storage_key(self):
        first_id = self.app.create_folder(self.project_id, "First")
        second_id = self.app.create_folder(self.project_id, "Second")
        file_id = self.app.create_file(
            self.project_id,
            "old.txt",
            b"payload",
            folder_id=first_id,
        )

        before = self.app.get_file(file_id)
        self.app.rename_file(file_id, "new.txt")
        self.app.move_file(file_id, second_id)
        after = self.app.get_file(file_id)

        self.assertIsNotNone(before)
        self.assertIsNotNone(after)
        if before is None or after is None:
            self.fail("file metadata could not be retrieved")
        self.assertEqual(after["name"], "new.txt")
        self.assertEqual(after["folder_id"], second_id)
        self.assertEqual(after["storage_key"], before["storage_key"])
        self.assertEqual(self.app.read_file(file_id), b"payload")

    def test_file_lifecycle_and_delete_are_available_through_boundary(self):
        file_id = self.app.create_file(self.project_id, "remove.txt", b"payload")
        record = self.app.get_file(file_id)
        self.assertIsNotNone(record)
        if record is None:
            self.fail("file metadata could not be retrieved")
        storage_key = record["storage_key"]

        self.app.set_file_lifecycle(file_id, "Archived")
        self.assertEqual(self.app.get_file(file_id)["lifecycle_status"], "Archived")
        self.assertTrue(file_storage.exists(self.temp_dir.name, storage_key))

        self.assertTrue(self.app.delete_file(file_id))
        self.assertIsNone(self.app.get_file(file_id))
        self.assertFalse(file_storage.exists(self.temp_dir.name, storage_key))

    def test_missing_records_are_reported_without_tuple_leakage(self):
        self.assertIsNone(self.app.get_folder(9999))
        self.assertIsNone(self.app.get_file(9999))

        with self.assertRaises(ValueError):
            self.app.read_file(9999)
        with self.assertRaises(ValueError):
            self.app.verify_file(9999)

    def test_empty_folder_deletion_remains_safe(self):
        folder_id = self.app.create_folder(self.project_id, "Empty")
        self.app.delete_folder(folder_id)
        self.assertIsNone(self.app.get_folder(folder_id))

    def test_non_empty_folder_deletion_is_rejected(self):
        folder_id = self.app.create_folder(self.project_id, "Documents")
        self.app.create_file(
            self.project_id,
            "report.txt",
            b"report",
            folder_id=folder_id,
        )

        with self.assertRaises(ValueError):
            self.app.delete_folder(folder_id)
        self.assertIsNotNone(self.app.get_folder(folder_id))


if __name__ == "__main__":
    unittest.main()
