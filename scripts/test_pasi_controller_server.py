from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from scripts.pasi_controller_server import (
    CONTROLLER_PATH,
    MANIFEST_PATH,
    RECOVERY_PATH,
    git_blob_sha1,
    load_verified_recovery,
    load_verified_release,
)


class TestPasiControllerServer(unittest.TestCase):
    def test_manifest_controller_and_recovery_are_present(self) -> None:
        self.assertTrue(MANIFEST_PATH.is_file())
        self.assertTrue(CONTROLLER_PATH.is_file())
        self.assertTrue(RECOVERY_PATH.is_file())

    def test_local_release_matches_published_git_blob(self) -> None:
        manifest, source, actual_sha = load_verified_release()
        self.assertEqual(actual_sha, manifest["git_blob_sha"])
        self.assertIn(f"@version      {manifest['version']}", source)

    def test_local_recovery_matches_published_git_blob(self) -> None:
        manifest, source, actual_sha = load_verified_recovery()
        self.assertEqual(actual_sha, manifest["recovery_git_blob_sha"])
        self.assertIn("GENERATION_TIMEOUT_MS", source)
        self.assertEqual(manifest["recovery_version"], "1.0.1")

    def test_git_blob_hash_uses_git_blob_header(self) -> None:
        payload = b"hello\n"
        expected = hashlib.sha1(b"blob 6\0" + payload).hexdigest()
        with tempfile.NamedTemporaryFile(delete=False) as temporary:
            path = Path(temporary.name)
            temporary.write(payload)
        try:
            self.assertEqual(git_blob_sha1(path), expected)
        finally:
            path.unlink()


if __name__ == "__main__":
    unittest.main()
