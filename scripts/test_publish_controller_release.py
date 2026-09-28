from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import scripts.publish_controller_release as publisher


class PublishControllerReleaseTests(unittest.TestCase):
    def test_release_publisher_preserves_and_refreshes_controller_and_recovery_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            controller = root / "controller.user.js"
            recovery = root / "recovery.js"
            manifest = root / "controller-sync.json"

            controller.write_text("// ==UserScript==\n// @version      7.8.9\n// ==/UserScript==\n", encoding="utf-8")
            recovery.write_text("const RECOVERY_VERSION = '3.2.1';\n", encoding="utf-8")
            manifest.write_text(
                json.dumps({
                    "schema_version": "1",
                    "enabled": True,
                    "version": "7.8.8",
                    "git_blob_sha": "1" * 40,
                    "recovery_version": "3.2.0",
                    "recovery_git_blob_sha": "2" * 40,
                    "reason": "previous",
                    "custom_field": "preserve-me",
                }),
                encoding="utf-8",
            )

            def fake_run(command: list[str]) -> str:
                if command == ["git", "branch", "--show-current"]:
                    return "main"
                if command == ["git", "status", "--short"]:
                    return ""
                if command[:2] == ["git", "hash-object"]:
                    path = command[2]
                    return "a" * 40 if path.endswith("controller.user.js") else "b" * 40
                if command == ["git", "rev-parse", "HEAD"]:
                    return "c" * 40
                return ""

            argv = ["publish_controller_release.py", "--version", "7.8.9", "--reason", "verified"]
            with patch.object(publisher, "REPOSITORY_ROOT", root),                  patch.object(publisher, "CONTROLLER_PATH", controller),                  patch.object(publisher, "RECOVERY_PATH", recovery),                  patch.object(publisher, "MANIFEST_PATH", manifest),                  patch.object(publisher, "REQUEST_PATH", root / "request.json"),                  patch.object(publisher, "run", side_effect=fake_run),                  patch.object(sys, "argv", argv):
                self.assertEqual(publisher.main(), 0)

            payload = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(payload["version"], "7.8.9")
            self.assertEqual(payload["git_blob_sha"], "a" * 40)
            self.assertEqual(payload["recovery_version"], "3.2.1")
            self.assertEqual(payload["recovery_git_blob_sha"], "b" * 40)
            self.assertEqual(payload["release_commit"], "c" * 40)
            self.assertEqual(payload["reason"], "verified")
            self.assertEqual(payload["custom_field"], "preserve-me")
            self.assertIn("/refs/heads/main/", payload["source_url"])
            self.assertIn("/refs/heads/main/", payload["recovery_source_url"])

    def test_source_versions_are_semantic(self) -> None:
        self.assertRegex(publisher.read_version(), r"^\d+\.\d+\.\d+$")
        self.assertRegex(publisher.read_recovery_version(), r"^\d+\.\d+\.\d+$")


if __name__ == "__main__":
    unittest.main()
