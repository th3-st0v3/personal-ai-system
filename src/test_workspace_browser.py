import os
import tempfile
import unittest

import db
import workspace_browser


class TestWorkspaceBrowser(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_db = db.DATABASE_PATH
        db.DATABASE_PATH = os.path.join(self.temp.name, "beta.db")
        connection = db.get_connection()
        try:
            self.project_id = db.create_project("Beta Project", "rich workspace")
        finally:
            connection.close()
        self.storage = os.path.join(self.temp.name, "storage")

    def tearDown(self):
        db.DATABASE_PATH = self.original_db
        self.temp.cleanup()

    def test_nested_notes_and_files_share_one_listing(self):
        root = workspace_browser.create_note(self.project_id, "Root Note", "hello")
        outer = __import__("workspace_storage").create_folder(self.project_id, "Engineering")
        inner = __import__("workspace_storage").create_folder(self.project_id, "Calculations", outer)
        nested = workspace_browser.create_note(self.project_id, "Pressure", "P=rho*g*h", inner)
        file_id = workspace_browser.create_file(self.storage, self.project_id, "data.csv", b"x,y\n1,2", "text/csv", inner)

        names = {(item.kind, item.name) for item in workspace_browser.list_children(self.project_id, inner)}
        self.assertEqual(names, {("note", "Pressure"), ("file", "data.csv")})
        self.assertNotEqual(root, nested)
        self.assertGreater(file_id, 0)

    def test_sort_options_are_explicit(self):
        workspace_browser.create_note(self.project_id, "zeta", "")
        workspace_browser.create_note(self.project_id, "Alpha", "")
        workspace_storage = __import__("workspace_storage")
        workspace_storage.create_folder(self.project_id, "Beta")
        self.assertEqual([i.name for i in workspace_browser.list_children(self.project_id, sort="a_z")], ["Alpha", "Beta", "zeta"])
        self.assertEqual([i.name for i in workspace_browser.list_children(self.project_id, sort="z_a")], ["zeta", "Beta", "Alpha"])
        self.assertEqual(len(workspace_browser.list_children(self.project_id, sort="last_modified_new_old")), 3)

    def test_item_specific_context_actions(self):
        folder = __import__("workspace_storage").create_folder(self.project_id, "Folder")
        note = workspace_browser.create_note(self.project_id, "Note", "", folder)
        file_id = workspace_browser.create_file(self.storage, self.project_id, "x.txt", b"x", "text/plain", folder)
        self.assertIn("new_note", workspace_browser.get_context_actions("folder"))
        self.assertIn("edit", workspace_browser.get_context_actions("note"))
        self.assertIn("preview", workspace_browser.get_context_actions("file"))
        self.assertNotIn("preview", workspace_browser.get_context_actions("folder"))
        self.assertEqual(set(workspace_browser.get_context_actions("file", selection_count=2)), {"open", "copy", "move", "delete", "properties"})
        self.assertEqual(workspace_browser.get_breadcrumbs("note", note)[-1][2], "Folder")
        self.assertEqual(workspace_browser.get_breadcrumbs("file", file_id)[-1][2], "Folder")

    def test_move_supports_drag_drop_semantics_and_prevents_folder_cycles(self):
        storage = __import__("workspace_storage")
        first = storage.create_folder(self.project_id, "First")
        second = storage.create_folder(self.project_id, "Second")
        note = workspace_browser.create_note(self.project_id, "Move me", "", first)
        workspace_browser.move_item("note", note, second)
        self.assertEqual(workspace_browser.get_note(note).parent_id, second)
        storage.move_folder(second, first)
        with self.assertRaises(ValueError):
            storage.move_folder(first, second)

    def test_delete_all_files_preserves_notes_and_folders(self):
        storage = __import__("workspace_storage")
        folder = storage.create_folder(self.project_id, "Data")
        workspace_browser.create_note(self.project_id, "Keep", "keep", folder)
        first = workspace_browser.create_file(self.storage, self.project_id, "a.txt", b"a", "text/plain", folder)
        second = workspace_browser.create_file(self.storage, self.project_id, "b.txt", b"b", "text/plain", folder)
        self.assertEqual(workspace_browser.delete_all_files(self.storage, self.project_id, folder), 2)
        self.assertEqual([i.name for i in workspace_browser.list_children(self.project_id, folder)], ["Keep"])
        self.assertFalse(os.path.exists(os.path.join(self.storage, "files")))
        self.assertIsNotNone(first); self.assertIsNotNone(second)

    def test_selection_delete_avoids_double_delete_for_nested_folder_selection(self):
        storage = __import__("workspace_storage")
        parent = storage.create_folder(self.project_id, "Parent")
        child = storage.create_folder(self.project_id, "Child", parent)
        workspace_browser.create_note(self.project_id, "N", "", child)
        count = workspace_browser.delete_selection(self.storage, self.project_id, [("folder", parent), ("folder", child)])
        self.assertEqual(count, 1)
        self.assertIsNone(storage.get_folder(parent))
        self.assertIsNone(storage.get_folder(child))


if __name__ == "__main__":
    unittest.main()
