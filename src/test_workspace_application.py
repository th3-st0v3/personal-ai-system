import os
import tempfile
import unittest

import db
from workspace_application import WorkspaceApplication


class TestWorkspaceApplication(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_db = db.DATABASE_PATH
        db.DATABASE_PATH = os.path.join(self.temp.name, "workspace.db")
        self.app = WorkspaceApplication(os.path.join(self.temp.name, "storage"))
        self.project_id = self.app.create_project("Workspace Project")

    def tearDown(self):
        db.DATABASE_PATH = self.original_db
        self.temp.cleanup()

    def test_nested_folders_notes_and_files(self):
        root = self.app.create_folder(self.project_id, "Engineering")
        child = self.app.create_folder(self.project_id, "Hydraulics", root)
        note = self.app.create_note(self.project_id, "Pressure Note", "hydrostatic pressure", child)
        file_id = self.app.create_file(self.project_id, "data.txt", b"123", "text/plain", child)
        items = self.app.list_children(self.project_id, child)
        self.assertEqual([item.name for item in items], ["Pressure Note", "data.txt"])
        self.assertEqual(self.app.get_note(note).content, "hydrostatic pressure")
        self.assertEqual(self.app.read_file(file_id, project_id=self.project_id), b"123")

    def test_selection_and_drag_drop_semantics(self):
        root = self.app.create_folder(self.project_id, "Engineering")
        child = self.app.create_folder(self.project_id, "Hydraulics", root)
        note = self.app.create_note(self.project_id, "Pressure", "content", root)
        self.app.select("note", note)
        self.app.select("folder", child, append=True)
        selection = self.app.current_selection()
        self.assertEqual({item.kind for item in selection}, {"note", "folder"})
        self.app.move_item("note", note, child, project_id=self.project_id)
        self.assertEqual(self.app.get_note(note).parent_id, child)

    def test_search_sort_and_properties(self):
        root = self.app.create_folder(self.project_id, "Engineering")
        child = self.app.create_folder(self.project_id, "Hydraulics", root)
        self.app.create_note(self.project_id, "Pressure Note", "hydrostatic pressure", child)
        self.app.create_file(self.project_id, "data.txt", b"123", "text/plain", child)
        matches = self.app.search_project(self.project_id, "hydrostatic")
        self.assertEqual([item.name for item in matches], ["Pressure Note"])
        properties = self.app.get_item_properties("note", matches[0].id)
        self.assertEqual(properties["name"], "Pressure Note")

    def test_copy_paste_and_duplicate(self):
        source = self.app.create_folder(self.project_id, "Source")
        target = self.app.create_folder(self.project_id, "Target")
        note = self.app.create_note(self.project_id, "Read me", "copy me", source)
        file_id = self.app.create_file(self.project_id, "data.txt", b"123", "text/plain", source)
        selection = [("note", note), ("file", file_id)]
        self.app.copy_selection(self.project_id, selection)
        created = self.app.paste_selection(self.project_id, target, selection)
        self.assertEqual(len(created), 2)
        pasted = self.app.list_children(self.project_id, target)
        self.assertEqual({item.name for item in pasted}, {"Read me", "data.txt"})
        duplicate_id = self.app.duplicate_item(self.project_id, "note", note)
        duplicated = self.app.get_note(duplicate_id)
        if duplicated is None:
            self.fail("duplicated note should exist")
        self.assertEqual(duplicated.name, "Read me (copy)")

    def test_project_isolation(self):
        other_project = self.app.create_project("Other")
        other_folder = self.app.create_folder(other_project, "Other")
        other_note = self.app.create_note(other_project, "Secret", "secret", other_folder)
        other_file = self.app.create_file(other_project, "secret.txt", b"secret")
        other_tag = self.app.create_tag(other_project, "private")
        target_folder = self.app.create_folder(self.project_id, "Target")
        with self.assertRaises(ValueError):
            self.app.read_file(other_file, project_id=self.project_id)
        with self.assertRaises(ValueError):
            self.app.verify_file(other_file, project_id=self.project_id)
        with self.assertRaises(ValueError):
            self.app.rename_file(other_file, "changed.txt", project_id=self.project_id)
        with self.assertRaises(ValueError):
            self.app.move_file(other_file, target_folder, project_id=self.project_id)
        with self.assertRaises(ValueError):
            self.app.delete_file(other_file, project_id=self.project_id)
        with self.assertRaises(ValueError):
            self.app.rename_folder(other_folder, "changed", project_id=self.project_id)
        with self.assertRaises(ValueError):
            self.app.move_note(other_note, None, project_id=self.project_id)
        with self.assertRaises(ValueError):
            self.app.delete_note(other_note, project_id=self.project_id)
        with self.assertRaises(ValueError):
            self.app.assign_tag(other_tag, "file", other_file, project_id=self.project_id)
        self.assertIsNotNone(self.app.get_file(other_file))
        self.assertIsNotNone(self.app.get_folder(other_folder))
        other_note_record = self.app.get_note(other_note)
        if other_note_record is None:
            self.fail("other-project note should exist")
        self.assertEqual(other_note_record.content, "secret")

    def test_invalid_browser_kind_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unsupported item kind"):
            self.app.get_item_properties("unsupported", 1)
        with self.assertRaisesRegex(ValueError, "Unsupported item kind"):
            self.app.rename_item("unsupported", 1, "renamed", project_id=self.project_id)
        with self.assertRaisesRegex(ValueError, "Unsupported item kind"):
            self.app.move_item("unsupported", 1, project_id=self.project_id)

    def test_file_lifecycle_and_delete_are_available_through_boundary(self):
        file_id = self.app.create_file(self.project_id, "remove.txt", b"payload")
        record = self.app.get_file(file_id)
        self.assertIsNotNone(record)
        self.app.set_file_lifecycle(file_id, "Archived", project_id=self.project_id)
        self.assertEqual(self.app.get_file(file_id)["lifecycle_status"], "Archived")
        self.assertEqual(self.app.delete_selection(self.project_id, [("file", file_id)]), 1)
        self.assertIsNone(self.app.get_file(file_id))


if __name__ == "__main__": unittest.main()
