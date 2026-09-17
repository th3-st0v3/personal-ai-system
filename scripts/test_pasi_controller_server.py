from __future__ import annotations

import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import scripts.pasi_controller_server as server
from scripts.pasi_controller_server import (
    CONTROLLER_PATH,
    MANIFEST_PATH,
    RECOVERY_PATH,
    ControllerDistributionError,
    git_blob_sha1,
    load_verified_canonical_bundle,
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
        self.assertEqual(manifest["recovery_version"], "1.0.5")

    def test_git_show_preserves_crlf_bytes(self) -> None:
        payload = b"controller-bytes\r\n"
        completed = subprocess.CompletedProcess(
            args=["git", "show", "origin/main:controller.js"],
            returncode=0,
            stdout=payload,
            stderr=b"",
        )
        with patch.object(server.subprocess, "run", return_value=completed) as run:
            self.assertEqual(
                server._git_show("origin/main", "controller.js"),
                payload,
            )
            self.assertIs(run.call_args.kwargs["text"], False)

    def test_canonical_bundle_reads_verified_origin_main_blobs(self) -> None:
        controller = "// @version      7.8.9\nconsole.log('controller');\n"
        recovery = "const RECOVERY_VERSION = '3.2.1';\nconsole.log('recovery');\n"
        with patch.object(server, "refresh_remote_main", return_value=True):
            with patch.object(server, "_git_ref_sha", return_value="a" * 40):
                def fake_show(ref: str, path: str) -> bytes:
                    self.assertEqual(ref, server.REMOTE_MAIN_REF)
                    return controller.encode() if path.endswith("chatgpt-controller.user.js") else recovery.encode()

                with patch.object(server, "_git_show", side_effect=fake_show):
                    manifest, actual_controller, controller_sha, actual_recovery, recovery_sha = load_verified_canonical_bundle()
        controller_bytes = controller.encode()
        recovery_bytes = recovery.encode()
        expected_controller_sha = hashlib.sha1(f"blob {len(controller_bytes)}\0".encode() + controller_bytes).hexdigest()
        expected_recovery_sha = hashlib.sha1(f"blob {len(recovery_bytes)}\0".encode() + recovery_bytes).hexdigest()
        self.assertEqual(actual_controller, controller)
        self.assertEqual(controller_sha, expected_controller_sha)
        self.assertEqual(actual_recovery, recovery)
        self.assertEqual(recovery_sha, expected_recovery_sha)
        self.assertEqual(manifest["git_blob_sha"], "a" * 40)
        self.assertEqual(manifest["recovery_git_blob_sha"], "a" * 40)

    def test_refresh_remote_main_uses_fetch_head(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["git", "fetch", "origin", "main"],
            returncode=0,
            stdout="",
            stderr="",
        )
        with patch.object(server.subprocess, "run", return_value=completed) as run:
            self.assertTrue(server.refresh_remote_main())
            self.assertEqual(run.call_args.args[0][0:4], ["git", "fetch", "--prune", "origin"])

    def test_load_verified_release_fails_closed_on_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path = root / "manifest.json"
            controller_path = root / "controller.js"
            manifest_path.write_text('{"version":"1.0.0","git_blob_sha":"deadbeef"}\n', encoding="utf-8")
            controller_path.write_text("// controller\n", encoding="utf-8")
            with patch.object(server, "MANIFEST_PATH", manifest_path), patch.object(server, "CONTROLLER_PATH", controller_path):
                with self.assertRaises(ControllerDistributionError):
                    server.load_verified_release()
