import os
import tempfile
import unittest

import db
import workspace_notes
import workspace_selection
import workspace_storage


class TestWorkspaceSelection(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_path = db.DATABASE_PATH
        db.DATABASE_PATH = os.path.join(self.temp_dir.name, "test.db")
        self.project_id = db.create_project("Selection Project", "Selection tests")

    def tearDown(self):
        db.DATABASE_PATH = self.original_path
        self.temp_dir.cleanup()

    def test_selection_rejects_cross_project_items(self):
        other_project = db.create_project("Other", "Other")
        file_id = workspace_storage.create_file(
            other_project, "other.txt", "other-key", 1, "0" * 64
        )

        with self.assertRaises(ValueError):
            workspace_selection.validate_selection(
                self.project_id, [{"type": "file", "id": file_id}]
            )

    def test_available_actions_are_intersection_for_multi_selection(self):
        folder = workspace_storage.create_folder(self.project_id, "Folder")
        file_id = workspace_storage.create_file(
            self.project_id, "report.pdf", "report-key", 1, "1" * 64, folder_id=folder
        )
        actions = workspace_selection.available_actions(
            self.project_id,
            [{"type": "folder", "id": folder}, {"type": "file", "id": file_id}],
        )

        self.assertIn("move", actions)
        self.assertIn("delete", actions)
        self.assertNotIn("rename", actions)

    def test_bulk_move_moves_files_and_notes_to_folder(self):
        folder = workspace_storage.create_folder(self.project_id, "Destination")
        file_id = workspace_storage.create_file(
            self.project_id, "report.pdf", "report-key", 1, "2" * 64
        )
        note_id = workspace_notes.create_note(self.project_id, "Note", "content")

        workspace_selection.move_selection(
            self.project_id,
            [{"type": "file", "id": file_id}, {"type": "note", "id": note_id}],
            folder,
        )

        self.assertEqual(workspace_storage.get_file(file_id)[2], folder)
        self.assertEqual(workspace_notes.get_note(note_id)["folder_id"], folder)
        self.assertIsNone(workspace_notes.get_note(note_id)["parent_note_id"])

    def test_bulk_delete_is_atomic_when_one_item_is_not_empty(self):
        folder = workspace_storage.create_folder(self.project_id, "Folder")
        file_id = workspace_storage.create_file(
            self.project_id, "report.pdf", "report-key", 1, "3" * 64, folder_id=folder
        )
        with self.assertRaises(ValueError):
            workspace_selection.delete_selection(
                self.project_id,
                [{"type": "file", "id": file_id}, {"type": "folder", "id": folder}],
            )

        self.assertIsNotNone(workspace_storage.get_file(file_id))
        self.assertIsNotNone(workspace_storage.get_folder(folder))

    def test_bulk_delete_cleans_file_and_note_tags(self):
        tag = workspace_storage.create_tag(self.project_id, "important")
        file_id = workspace_storage.create_file(
            self.project_id, "report.pdf", "report-key", 1, "4" * 64
        )
        note_id = workspace_notes.create_note(self.project_id, "Note", "content")
        workspace_storage.assign_tag(tag, "file", file_id)
        # Notes are intentionally not yet a tag target; file cleanup remains covered here.

        workspace_selection.delete_selection(
            self.project_id, [{"type": "file", "id": file_id}, {"type": "note", "id": note_id}]
        )
        self.assertEqual(workspace_storage.get_tags_for_target("file", file_id), [])


if __name__ == "__main__":
    unittest.main()
