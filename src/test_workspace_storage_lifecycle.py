import hashlib
import os
import sqlite3
import tempfile
import unittest

import db
import workspace_storage


class TestWorkspaceStorageLifecycle(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_path = db.DATABASE_PATH
        db.DATABASE_PATH = os.path.join(self.temp_dir.name, "test.db")
        self.project_id = db.create_project("Project A")
        self.digest = hashlib.sha256(b"example").hexdigest()

    def tearDown(self):
        db.DATABASE_PATH = self.original_path
        self.temp_dir.cleanup()

    def test_file_lifecycle_transitions_are_idempotent(self):
        file_id = workspace_storage.create_file(
            self.project_id, "data.csv", "objects/data.csv", 10, self.digest
        )

        workspace_storage.update_file_lifecycle_status(file_id, "Archived")
        self.assertEqual(workspace_storage.get_file(file_id)[8], "Archived")
        workspace_storage.update_file_lifecycle_status(file_id, "Archived")
        self.assertEqual(workspace_storage.get_file(file_id)[8], "Archived")

        workspace_storage.update_file_lifecycle_status(file_id, "Active")
        self.assertEqual(workspace_storage.get_file(file_id)[8], "Active")
        workspace_storage.update_file_lifecycle_status(file_id, "Invalidated")
        self.assertEqual(workspace_storage.get_file(file_id)[8], "Invalidated")
        workspace_storage.update_file_lifecycle_status(file_id, "Invalidated")
        self.assertEqual(workspace_storage.get_file(file_id)[8], "Invalidated")
        workspace_storage.update_file_lifecycle_status(file_id, "Active")
        self.assertEqual(workspace_storage.get_file(file_id)[8], "Active")

    def test_folder_lifecycle_transitions_are_idempotent(self):
        folder_id = workspace_storage.create_folder(self.project_id, "Documents")

        workspace_storage.update_folder_lifecycle_status(folder_id, "Archived")
        self.assertEqual(workspace_storage.get_folder(folder_id)[4], "Archived")
        workspace_storage.update_folder_lifecycle_status(folder_id, "Archived")
        self.assertEqual(workspace_storage.get_folder(folder_id)[4], "Archived")

        workspace_storage.update_folder_lifecycle_status(folder_id, "Active")
        self.assertEqual(workspace_storage.get_folder(folder_id)[4], "Active")
        workspace_storage.update_folder_lifecycle_status(folder_id, "Invalidated")
        self.assertEqual(workspace_storage.get_folder(folder_id)[4], "Invalidated")
        workspace_storage.update_folder_lifecycle_status(folder_id, "Invalidated")
        self.assertEqual(workspace_storage.get_folder(folder_id)[4], "Invalidated")
        workspace_storage.update_folder_lifecycle_status(folder_id, "Active")
        self.assertEqual(workspace_storage.get_folder(folder_id)[4], "Active")

    def test_delete_file_cleans_tags_and_attachments(self):
        file_id = workspace_storage.create_file(
            self.project_id, "report.pdf", "objects/report.pdf", 10, self.digest
        )
        tag_id = workspace_storage.create_tag(self.project_id, "Important")
        workspace_storage.assign_tag(tag_id, "file", file_id)
        well_id = db.create_well(self.project_id, "Well-1")
        workspace_storage.attach_file(file_id, "well", well_id)

        workspace_storage.delete_file(file_id)

        self.assertIsNone(workspace_storage.get_file(file_id))
        self.assertEqual(workspace_storage.get_tags(self.project_id)[0][0], tag_id)
        connection = db.get_connection()
        try:
            assignment = connection.execute(
                "SELECT 1 FROM tag_assignments "
                "WHERE tag_id = ? AND target_type = ? AND target_id = ?",
                (tag_id, "file", file_id),
            ).fetchone()
            attachment = connection.execute(
                "SELECT 1 FROM attachments WHERE file_id = ?",
                (file_id,),
            ).fetchone()
        finally:
            connection.close()
        self.assertIsNone(assignment)
        self.assertIsNone(attachment)

    def test_bulk_delete_cleans_tags_and_attachments(self):
        first_file_id = workspace_storage.create_file(
            self.project_id, "first.pdf", "objects/first.pdf", 10, self.digest
        )
        second_file_id = workspace_storage.create_file(
            self.project_id, "second.pdf", "objects/second.pdf", 10, self.digest
        )
        tag_id = workspace_storage.create_tag(self.project_id, "Important")
        workspace_storage.assign_tag(tag_id, "file", first_file_id)
        workspace_storage.assign_tag(tag_id, "file", second_file_id)
        well_id = db.create_well(self.project_id, "Well-1")
        workspace_storage.attach_file(first_file_id, "well", well_id)
        workspace_storage.attach_file(second_file_id, "well", well_id)

        workspace_storage.delete_files([first_file_id, second_file_id])

        self.assertEqual(workspace_storage.get_tags(self.project_id)[0][0], tag_id)
        connection = db.get_connection()
        try:
            assignments = connection.execute(
                "SELECT target_id FROM tag_assignments "
                "WHERE tag_id = ? AND target_type = ? ORDER BY target_id",
                (tag_id, "file"),
            ).fetchall()
            attachments = connection.execute(
                "SELECT file_id FROM attachments WHERE file_id IN (?, ?) ORDER BY file_id",
                (first_file_id, second_file_id),
            ).fetchall()
        finally:
            connection.close()
        self.assertEqual(assignments, [])
        self.assertEqual(attachments, [])

    def test_delete_empty_folder_cleans_tag_assignments(self):
        folder_id = workspace_storage.create_folder(self.project_id, "Empty")
        tag_id = workspace_storage.create_tag(self.project_id, "Important")
        workspace_storage.assign_tag(tag_id, "folder", folder_id)

        workspace_storage.delete_folder(folder_id)

        self.assertIsNone(workspace_storage.get_folder(folder_id))
        self.assertEqual(workspace_storage.get_tags(self.project_id)[0][0], tag_id)
        connection = db.get_connection()
        try:
            assignment = connection.execute(
                "SELECT 1 FROM tag_assignments "
                "WHERE tag_id = ? AND target_type = ? AND target_id = ?",
                (tag_id, "folder", folder_id),
            ).fetchone()
        finally:
            connection.close()
        self.assertIsNone(assignment)

    def test_delete_archived_file_still_removes_file(self):
        file_id = workspace_storage.create_file(
            self.project_id, "archived.txt", "objects/archived.txt", 10, self.digest
        )
        workspace_storage.update_file_lifecycle_status(file_id, "Archived")

        workspace_storage.delete_file(file_id)

        self.assertIsNone(workspace_storage.get_file(file_id))


if __name__ == "__main__":
    unittest.main()
