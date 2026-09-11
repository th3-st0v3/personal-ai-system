import os
import tempfile
import unittest

import db
import project_workspace
import workspace_notes
import workspace_storage


class TestProjectWorkspace(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_path = db.DATABASE_PATH
        db.DATABASE_PATH = os.path.join(self.temp_dir.name, "test.db")
        self.project_id = db.create_project("Beta Project", "Engineering work")

    def tearDown(self):
        db.DATABASE_PATH = self.original_path
        self.temp_dir.cleanup()

    def test_project_is_a_workspace_with_tools(self):
        workspace = project_workspace.get_project_workspace(self.project_id)

        self.assertEqual(workspace["project"]["name"], "Beta Project")
        self.assertIn("folders", workspace["tools"])
        self.assertIn("notes", workspace["tools"])
        self.assertIn("calculations", workspace["tools"])
        self.assertIn("requirements", workspace["tools"])

    def test_notes_support_arbitrary_parenting_and_safe_cycle_detection(self):
        root = workspace_notes.create_note(self.project_id, "Root note", "Root content")
        child = workspace_notes.create_note(
            self.project_id, "Child note", "Child content", parent_note_id=root
        )
        grandchild = workspace_notes.create_note(
            self.project_id, "Grandchild note", "Grandchild content", parent_note_id=child
        )

        self.assertEqual(workspace_notes.list_notes(self.project_id, parent_note_id=root)[0]["id"], child)
        self.assertEqual(workspace_notes.list_notes(self.project_id, parent_note_id=child)[0]["id"], grandchild)

        with self.assertRaises(ValueError):
            workspace_notes.move_note(root, parent_note_id=grandchild)

    def test_notes_can_live_inside_folders_and_are_sorted(self):
        folder = workspace_storage.create_folder(self.project_id, "Notes")
        workspace_notes.create_note(self.project_id, "Zeta", "z", folder_id=folder)
        workspace_notes.create_note(self.project_id, "Alpha", "a", folder_id=folder)

        notes = workspace_notes.list_notes(self.project_id, folder_id=folder, sort="name_asc")
        self.assertEqual([note["title"] for note in notes], ["Alpha", "Zeta"])

    def test_note_delete_requires_leaf_notes(self):
        parent = workspace_notes.create_note(self.project_id, "Parent", "parent")
        workspace_notes.create_note(self.project_id, "Child", "child", parent_note_id=parent)

        with self.assertRaises(ValueError):
            workspace_notes.delete_note(parent)

    def test_project_root_lists_folders_files_and_notes_with_context_actions(self):
        folder = workspace_storage.create_folder(self.project_id, "Folder")
        workspace_storage.create_file(
            self.project_id, "report.pdf", "files/test-report", 4, "0" * 64, "application/pdf"
        )
        workspace_notes.create_note(self.project_id, "Design Notes", "content")

        items = project_workspace.list_children(self.project_id, sort="name_asc")

        self.assertEqual([item["type"] for item in items], ["note", "file", "folder"])
        self.assertEqual(items[0]["name"], "Design Notes")
        self.assertEqual(items[0]["location_type"], "project")
        self.assertIn("open", items[0]["actions"])
        self.assertNotIn("tag", items[0]["actions"])
        self.assertIn("delete", items[1]["actions"])
        self.assertEqual(items[2]["id"], folder)
        self.assertEqual(items[2]["location_type"], "project")

    def test_context_actions_change_for_selection_and_lifecycle(self):
        single = project_workspace.context_actions("file", "Active")
        multi = project_workspace.context_actions("file", "Active", selected_count=3)
        archived = project_workspace.context_actions("file", "Archived")

        self.assertIn("rename", single)
        self.assertNotIn("rename", multi)
        self.assertIn("delete", multi)
        self.assertIn("restore", archived)
        self.assertNotIn("archive", archived)


if __name__ == "__main__":
    unittest.main()
