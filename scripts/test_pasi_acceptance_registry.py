from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import pasi_acceptance_registry as registry


class AcceptanceRegistryTests(unittest.TestCase):
    def test_record_captures_code_controller_environment_and_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "automation" / "chromium" / "pasi-chatgpt").mkdir(parents=True)
            (root / "automation" / "chromium" / "pasi-chatgpt" / "content.js").write_text(
                "const CONTROLLER_VERSION = '2.4.11';\n", encoding="utf-8"
            )
            (root / "automation" / "chromium" / "pasi-chatgpt" / "manifest.json").write_text(
                json.dumps({"version": "1.2.0"}), encoding="utf-8"
            )
            subprocess = registry.subprocess
            with mock.patch.object(registry, "_run", side_effect=lambda cwd, *args: {
                ("rev-parse", "--show-toplevel"): str(root),
                ("rev-parse", "HEAD"): "a" * 40,
                ("branch", "--show-current"): "pasi/test",
                ("config", "--get", "remote.origin.url"): "https://github.com/th3-st0v3/personal-ai-system.git",
            }.get(args, "")):
                artifact = root / "m1-live.json"
                artifact.write_text(
                    json.dumps(
                        {
                            "gate": "M1",
                            "status": "PASS",
                            "provider": "chatgpt_browser",
                            "completed_at": 123,
                            "operation_id": "op-1",
                            "task_id": "task-1",
                            "results": [{"operation_id": "op-1"}, {"operation_id": "op-2"}],
                        }
                    ),
                    encoding="utf-8",
                )
                output = root / "registry.json"
                entry = registry.record_artifact(artifact, output)

            self.assertEqual(entry["gate"], "M1")
            self.assertEqual(entry["status"], "PASS")
            self.assertEqual(entry["provider"], "chatgpt_browser")
            self.assertEqual(entry["code"]["head_commit"], "a" * 40)
            self.assertEqual(entry["code"]["branch"], "pasi/test")
            self.assertEqual(entry["code"]["repository"], "th3-st0v3/personal-ai-system")
            self.assertEqual(entry["controller"]["content_version"], "2.4.11")
            self.assertEqual(entry["controller"]["manifest_version"], "1.2.0")
            self.assertEqual(entry["identity"]["operation_ids"], ["op-1", "op-2"])
            self.assertTrue(entry["artifact"]["sha256"])

    def test_record_is_idempotent_for_same_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".git").mkdir()
            artifact = root / "m0.json"
            artifact.write_text(json.dumps({"gate": "M0", "status": "PASS"}), encoding="utf-8")
            output = root / "registry.json"
            with mock.patch.object(registry, "_repo_root", return_value=root),                  mock.patch.object(registry, "build_entry", side_effect=lambda a, r, p: {
                     "artifact": {"sha256": registry._artifact_sha256(a), "path": str(a.resolve())},
                     "gate": "M0",
                 }):
                first = registry.record_artifact(artifact, output)
                second = registry.record_artifact(artifact, output)

            self.assertEqual(first, second)
            stored = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(len(stored), 1)


if __name__ == "__main__":
    unittest.main()
