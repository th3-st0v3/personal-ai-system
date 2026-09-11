import hashlib
import tempfile
import unittest
from unittest import mock

import file_storage
import workspace_file_service
import workspace_storage


class TestWorkspaceFileService(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = self.temp_dir.name
        self.project_id = self._create_project()

    def tearDown(self):
        self.temp_dir.cleanup()

    def _create_project(self):
        import db

        connection = db.get_connection()
        try:
            cursor = connection.execute(
                "INSERT INTO projects (name, description) VALUES (?, ?)",
                ("File Service Test", "file service boundary"),
            )
            connection.commit()
            return cursor.lastrowid
        finally:
            connection.close()

    def test_create_file_coordinates_bytes_and_metadata(self):
        payload = b"well evidence"
        file_id = workspace_file_service.create_file(
            self.root,
            self.project_id,
            "evidence.txt",
            payload,
            "text/plain",
        )

        record = workspace_storage.get_file(file_id)
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record[1], self.project_id)
        self.assertEqual(record[3], "evidence.txt")
        self.assertEqual(record[5], "text/plain")
        self.assertEqual(record[6], len(payload))
        self.assertEqual(record[7], hashlib.sha256(payload).hexdigest())
        self.assertEqual(file_storage.read_bytes(self.root, record[4]), payload)

    def test_create_file_generates_filename_independent_storage_key(self):
        first_id = workspace_file_service.create_file(
            self.root, self.project_id, "report-a.pdf", b"same", "application/pdf"
        )
        second_id = workspace_file_service.create_file(
            self.root, self.project_id, "renamed-report.pdf", b"same", "application/pdf"
        )

        first = workspace_storage.get_file(first_id)
        second = workspace_storage.get_file(second_id)
        self.assertNotEqual(first[4], second[4])
        self.assertTrue(first[4].startswith("files/"))
        self.assertTrue(second[4].startswith("files/"))

    def test_create_file_rolls_back_bytes_when_metadata_creation_fails(self):
        with mock.patch.object(
            workspace_storage,
            "create_file",
            side_effect=ValueError("metadata failure"),
        ):
            with self.assertRaises(ValueError):
                workspace_file_service.create_file(
                    self.root, self.project_id, "broken.txt", b"payload"
                )

        self.assertEqual(file_storage.storage_path(self.root, "files").exists(), False)
        self.assertEqual(workspace_storage.get_files(self.project_id), [])

    def test_delete_file_removes_metadata_and_bytes(self):
        file_id = workspace_file_service.create_file(
            self.root, self.project_id, "delete-me.txt", b"payload"
        )
        record = workspace_storage.get_file(file_id)
        storage_key = record[4]

        self.assertTrue(workspace_file_service.delete_file(self.root, file_id))
        self.assertIsNone(workspace_storage.get_file(file_id))
        self.assertFalse(file_storage.exists(self.root, storage_key))

    def test_delete_file_is_idempotent_at_byte_cleanup_boundary(self):
        file_id = workspace_file_service.create_file(
            self.root, self.project_id, "already-gone.txt", b"payload"
        )
        record = workspace_storage.get_file(file_id)
        file_storage.delete_bytes(self.root, record[4])

        self.assertFalse(workspace_file_service.delete_file(self.root, file_id))
        self.assertIsNone(workspace_storage.get_file(file_id))

    def test_delete_file_reports_physical_cleanup_failure_after_metadata_delete(self):
        file_id = workspace_file_service.create_file(
            self.root, self.project_id, "cleanup-fails.txt", b"payload"
        )
        record = workspace_storage.get_file(file_id)

        with mock.patch.object(
            file_storage,
            "delete_bytes",
            side_effect=OSError("storage unavailable"),
        ):
            with self.assertRaises(workspace_file_service.FileServiceError):
                workspace_file_service.delete_file(self.root, file_id)

        self.assertIsNone(workspace_storage.get_file(file_id))
        self.assertTrue(file_storage.exists(self.root, record[4]))


if __name__ == "__main__":
    unittest.main()
