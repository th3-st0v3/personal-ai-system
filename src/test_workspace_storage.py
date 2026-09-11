import hashlib
import os
import sqlite3
import tempfile
import unittest

import db
import workspace_storage


class TestWorkspaceStorage(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_path = db.DATABASE_PATH
        db.DATABASE_PATH = os.path.join(self.temp_dir.name, "test.db")
        self.project_id = db.create_project("Project A")
        self.other_project_id = db.create_project("Project B")
        self.digest = hashlib.sha256(b"example").hexdigest()

    def tearDown(self):
        db.DATABASE_PATH = self.original_path
        self.temp_dir.cleanup()

    def test_creates_nested_folders_and_lists_by_parent(self):
        root_id = workspace_storage.create_folder(self.project_id, "References")
        child_id = workspace_storage.create_folder(self.project_id, "Papers", root_id)

        root = workspace_storage.get_folder(root_id)
        children = workspace_storage.get_folders(self.project_id, root_id)

        self.assertEqual(root[3], "References")
        self.assertEqual(children[0][0], child_id)
        self.assertEqual(children[0][2], root_id)

    def test_rejects_cross_project_folder_parent(self):
        other_folder_id = workspace_storage.create_folder(self.other_project_id, "Other")

        with self.assertRaises(ValueError):
            workspace_storage.create_folder(self.project_id, "Invalid", other_folder_id)

    def test_prevents_duplicate_folder_names_in_same_parent(self):
        workspace_storage.create_folder(self.project_id, "References")

        with self.assertRaises(sqlite3.IntegrityError):
            workspace_storage.create_folder(self.project_id, "References")

    def test_moves_folder_without_creating_cycle(self):
        root_id = workspace_storage.create_folder(self.project_id, "Root")
        child_id = workspace_storage.create_folder(self.project_id, "Child", root_id)
        destination_id = workspace_storage.create_folder(self.project_id, "Destination")

        workspace_storage.move_folder(child_id, destination_id)
        self.assertEqual(workspace_storage.get_folder(child_id)[2], destination_id)

        with self.assertRaises(ValueError):
            workspace_storage.move_folder(root_id, child_id)

    def test_creates_file_and_enforces_project_folder_scope(self):
        folder_id = workspace_storage.create_folder(self.project_id, "Documents")
        file_id = workspace_storage.create_file(
            self.project_id,
            "report.pdf",
            "objects/report.pdf",
            7,
            self.digest,
            "application/pdf",
            folder_id,
        )

        stored = workspace_storage.get_file(file_id)
        self.assertEqual(stored[1], self.project_id)
        self.assertEqual(stored[2], folder_id)
        self.assertEqual(stored[7], self.digest)

        other_folder_id = workspace_storage.create_folder(self.other_project_id, "Other")
        with self.assertRaises(ValueError):
            workspace_storage.create_file(
                self.project_id,
                "bad.pdf",
                "objects/bad.pdf",
                1,
                self.digest,
                folder_id=other_folder_id,
            )

    def test_rejects_invalid_file_metadata(self):
        with self.assertRaises(ValueError):
            workspace_storage.create_file(self.project_id, "x", "x", -1, self.digest)
        with self.assertRaises(ValueError):
            workspace_storage.create_file(self.project_id, "x", "x2", 1, "not-a-sha")

    def test_moves_file_between_folders(self):
        first = workspace_storage.create_folder(self.project_id, "First")
        second = workspace_storage.create_folder(self.project_id, "Second")
        file_id = workspace_storage.create_file(
            self.project_id, "data.csv", "objects/data.csv", 10, self.digest, folder_id=first
        )

        workspace_storage.move_file(file_id, second)
        self.assertEqual(workspace_storage.get_file(file_id)[2], second)

    def test_file_lifecycle_and_delete(self):
        file_id = workspace_storage.create_file(
            self.project_id, "data.csv", "objects/data.csv", 10, self.digest
        )
        workspace_storage.update_file_lifecycle_status(file_id, "Archived")
        self.assertEqual(workspace_storage.get_file(file_id)[8], "Archived")

        workspace_storage.delete_file(file_id)
        self.assertIsNone(workspace_storage.get_file(file_id))

    def test_tags_are_project_scoped(self):
        tag_id = workspace_storage.create_tag(self.project_id, "verified-source")
        file_id = workspace_storage.create_file(
            self.project_id, "paper.pdf", "objects/paper.pdf", 10, self.digest
        )
        other_file_id = workspace_storage.create_file(
            self.other_project_id, "other.pdf", "objects/other.pdf", 10, self.digest
        )

        workspace_storage.assign_tag(tag_id, "file", file_id)
        self.assertEqual(workspace_storage.get_tags_for_target("file", file_id)[0][0], tag_id)

        with self.assertRaises(ValueError):
            workspace_storage.assign_tag(tag_id, "file", other_file_id)

    def test_attachments_are_project_scoped_and_idempotency_is_explicit(self):
        file_id = workspace_storage.create_file(
            self.project_id, "notes.txt", "objects/notes.txt", 5, self.digest
        )
        well_id = db.create_well(self.project_id, "Well-1")
        attachment_id = workspace_storage.attach_file(file_id, "well", well_id)

        self.assertEqual(workspace_storage.get_file_attachments(file_id)[0][0], attachment_id)

        with self.assertRaises(sqlite3.IntegrityError):
            workspace_storage.attach_file(file_id, "well", well_id)

    def test_attachment_rejects_cross_project_target(self):
        file_id = workspace_storage.create_file(
            self.project_id, "notes.txt", "objects/notes.txt", 5, self.digest
        )
        well_id = db.create_well(self.other_project_id, "Other-Well")

        with self.assertRaises(ValueError):
            workspace_storage.attach_file(file_id, "well", well_id)

    def test_delete_files_supports_bulk_delete(self):
        ids = [
            workspace_storage.create_file(
                self.project_id,
                f"file-{index}.txt",
                f"objects/file-{index}.txt",
                1,
                self.digest,
            )
            for index in range(3)
        ]

        workspace_storage.delete_files(ids + ids[:1])
        self.assertEqual(workspace_storage.get_files(self.project_id), [])

    def test_invalid_tag_target_type_is_rejected(self):
        tag_id = workspace_storage.create_tag(self.project_id, "reviewed")

        with self.assertRaises(ValueError):
            workspace_storage.assign_tag(tag_id, "calculation_record", 1)


if __name__ == "__main__":
    unittest.main()
