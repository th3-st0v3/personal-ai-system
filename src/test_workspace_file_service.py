import hashlib
import os
import tempfile
import unittest
from unittest import mock

import db
import file_storage
import workspace_file_service
import workspace_storage


class TestWorkspaceFileService(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = self.temp_dir.name
        self.original_path = db.DATABASE_PATH
        db.DATABASE_PATH = os.path.join(self.root, "test.db")
        self.project_id = db.create_project("File Service Test")

    def tearDown(self):
        db.DATABASE_PATH = self.original_path
        self.temp_dir.cleanup()

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
        if record is None:
            self.fail("created file metadata could not be retrieved")
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
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        if first is None or second is None:
            self.fail("created file metadata could not be retrieved")
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

        files_dir = os.path.join(self.root, "files")
        self.assertEqual(os.listdir(files_dir) if os.path.exists(files_dir) else [], [])
        self.assertEqual(workspace_storage.get_files(self.project_id), [])

    def test_delete_file_removes_metadata_and_bytes(self):
        file_id = workspace_file_service.create_file(
            self.root, self.project_id, "delete-me.txt", b"payload"
        )
        record = workspace_storage.get_file(file_id)
        self.assertIsNotNone(record)
        if record is None:
            self.fail("created file metadata could not be retrieved")
        storage_key = record[4]

        self.assertTrue(workspace_file_service.delete_file(self.root, file_id))
        self.assertIsNone(workspace_storage.get_file(file_id))
        self.assertFalse(file_storage.exists(self.root, storage_key))

    def test_delete_file_is_idempotent_at_byte_cleanup_boundary(self):
        file_id = workspace_file_service.create_file(
            self.root, self.project_id, "already-gone.txt", b"payload"
        )
        record = workspace_storage.get_file(file_id)
        self.assertIsNotNone(record)
        if record is None:
            self.fail("created file metadata could not be retrieved")
        file_storage.delete_bytes(self.root, record[4])

        self.assertTrue(workspace_file_service.delete_file(self.root, file_id))
        self.assertIsNone(workspace_storage.get_file(file_id))

    def test_delete_file_retains_invalidated_metadata_when_physical_cleanup_fails(self):
        file_id = workspace_file_service.create_file(
            self.root, self.project_id, "cleanup-fails.txt", b"payload"
        )
        record = workspace_storage.get_file(file_id)
        self.assertIsNotNone(record)
        if record is None:
            self.fail("created file metadata could not be retrieved")

        with mock.patch.object(
            file_storage,
            "delete_bytes",
            side_effect=OSError("storage unavailable"),
        ):
            with self.assertRaises(workspace_file_service.FileServiceError):
                workspace_file_service.delete_file(self.root, file_id)

        retained = workspace_storage.get_file(file_id)
        self.assertIsNotNone(retained)
        if retained is None:
            self.fail("invalidated metadata was unexpectedly removed")
        self.assertEqual(retained[8], "Invalidated")
        self.assertTrue(file_storage.exists(self.root, record[4]))

    def test_delete_files_removes_all_metadata_and_bytes(self):
        file_ids = [
            workspace_file_service.create_file(
                self.root, self.project_id, f"file-{index}.txt", f"data-{index}".encode()
            )
            for index in range(3)
        ]
        records = [workspace_storage.get_file(file_id) for file_id in file_ids]
        self.assertTrue(all(record is not None for record in records))
        storage_keys = [record[4] for record in records if record is not None]

        self.assertEqual(
            workspace_file_service.delete_files(self.root, [file_ids[0], file_ids[1], file_ids[1], file_ids[2]]),
            3,
        )
        self.assertEqual(workspace_storage.get_files(self.project_id), [])
        self.assertTrue(all(not file_storage.exists(self.root, key) for key in storage_keys))

    def test_delete_files_rejects_missing_file_without_deleting_existing_files(self):
        existing_id = workspace_file_service.create_file(
            self.root, self.project_id, "existing.txt", b"payload"
        )

        with self.assertRaises(ValueError):
            workspace_file_service.delete_files(self.root, [existing_id, 9999])

        self.assertIsNotNone(workspace_storage.get_file(existing_id))

    def test_delete_files_reports_physical_cleanup_failure_and_retains_tombstone(self):
        file_id = workspace_file_service.create_file(
            self.root, self.project_id, "cleanup-fails-bulk.txt", b"payload"
        )
        record = workspace_storage.get_file(file_id)
        self.assertIsNotNone(record)
        if record is None:
            self.fail("created file metadata could not be retrieved")

        with mock.patch.object(
            file_storage,
            "delete_bytes",
            side_effect=OSError("storage unavailable"),
        ):
            with self.assertRaises(workspace_file_service.FileServiceError):
                workspace_file_service.delete_files(self.root, [file_id])

        retained = workspace_storage.get_file(file_id)
        self.assertIsNotNone(retained)
        if retained is None:
            self.fail("invalidated metadata was unexpectedly removed")
        self.assertEqual(retained[8], "Invalidated")
        self.assertTrue(file_storage.exists(self.root, record[4]))

    def test_reconcile_storage_removes_orphans_and_reports_missing(self):
        file_id = workspace_file_service.create_file(
            self.root, self.project_id, "tracked.txt", b"payload"
        )
        record = workspace_storage.get_file(file_id)
        self.assertIsNotNone(record)
        if record is None:
            self.fail("created file metadata could not be retrieved")
        orphan_key = "files/orphan-object"
        file_storage.save_bytes(self.root, orphan_key, b"orphan")
        file_storage.delete_bytes(self.root, record[4])

        result = workspace_file_service.reconcile_storage(self.root)
        self.assertIn(orphan_key, result["orphaned"])
        self.assertIn(orphan_key, result["removed"])
        self.assertIn(record[4], result["missing"])
        self.assertFalse(file_storage.exists(self.root, orphan_key))


if __name__ == "__main__":
    unittest.main()
