import hashlib
import os
import tempfile
import unittest

import file_storage


class TestFileStorage(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = self.temp_dir.name

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_save_read_exists_and_digest(self):
        payload = b"petroleum engineering evidence"
        digest = file_storage.save_bytes(self.root, "project/report.bin", payload)

        self.assertEqual(digest, hashlib.sha256(payload).hexdigest())
        self.assertTrue(file_storage.exists(self.root, "project/report.bin"))
        self.assertEqual(file_storage.read_bytes(self.root, "project/report.bin"), payload)
        self.assertTrue(file_storage.verify_sha256(self.root, "project/report.bin", digest))
        self.assertFalse(file_storage.verify_sha256(self.root, "project/report.bin", "0" * 64))

    def test_save_replaces_existing_object_atomically(self):
        key = "objects/example.txt"
        file_storage.save_bytes(self.root, key, b"first")
        file_storage.save_bytes(self.root, key, b"second")

        self.assertEqual(file_storage.read_bytes(self.root, key), b"second")
        self.assertFalse(any(name.startswith(".example.txt.") for name in os.listdir(os.path.join(self.root, "objects"))))

    def test_delete_is_idempotent(self):
        key = "objects/example.txt"
        file_storage.save_bytes(self.root, key, b"data")

        self.assertTrue(file_storage.delete_bytes(self.root, key))
        self.assertFalse(file_storage.exists(self.root, key))
        self.assertFalse(file_storage.delete_bytes(self.root, key))

    def test_rejects_path_traversal_and_absolute_keys(self):
        for key in ("../outside.txt", "objects/../../outside.txt", "/tmp/outside.txt", "C:/outside.txt"):
            with self.assertRaises(ValueError):
                file_storage.storage_path(self.root, key)

    def test_rejects_empty_and_non_bytes_payloads(self):
        with self.assertRaises(ValueError):
            file_storage.storage_path(self.root, "")
        with self.assertRaises(TypeError):
            file_storage.save_bytes(self.root, "objects/example.txt", "not bytes")

    def test_verify_rejects_invalid_digest(self):
        file_storage.save_bytes(self.root, "objects/example.txt", b"data")
        for digest in ("", "abc", "z" * 64):
            with self.assertRaises(ValueError):
                file_storage.verify_sha256(self.root, "objects/example.txt", digest)


if __name__ == "__main__":
    unittest.main()
