from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import pasi_acceptance_registry as registry


class AcceptanceRegistryTests(unittest.TestCase):
    def _fixture_root(self, temp_dir: str) -> Path:
        root = Path(temp_dir)
        (root / ".runtime" / "acceptance").mkdir(parents=True)
        (root / "automation" / "chromium" / "pasi-chatgpt").mkdir(parents=True)
        (root / "automation" / "chromium" / "pasi-chatgpt" / "content.js").write_text(
            "const CONTROLLER_VERSION = '2.4.11';\n", encoding="utf-8"
        )
        (root / "automation" / "chromium" / "pasi-chatgpt" / "manifest.json").write_text(
            json.dumps({"version": "1.2.0"}), encoding="utf-8"
        )
        return root

    def test_record_captures_code_controller_environment_and_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = self._fixture_root(temp_dir)
            with mock.patch.dict(
                registry.os.environ,
                {
                    "GITHUB_SHA": "a" * 40,
                    "GITHUB_REF_NAME": "pasi/test",
                    "GITHUB_REPOSITORY": "th3-st0v3/personal-ai-system",
                },
                clear=False,
            ):
                artifact = root / ".runtime" / "acceptance" / "m1-live.json"
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
                entry = registry.record_gate("M1", output=output)

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
            root = self._fixture_root(temp_dir)
            artifact = root / ".runtime" / "acceptance" / "m0-live.json"
            artifact.write_text(json.dumps({"gate": "M0", "status": "PASS"}), encoding="utf-8")
            output = root / "registry.json"
            with mock.patch.dict(
                registry.os.environ,
                {
                    "GITHUB_SHA": "a" * 40,
                    "GITHUB_REF_NAME": "pasi/test",
                    "GITHUB_REPOSITORY": "th3-st0v3/personal-ai-system",
                },
                clear=False,
            ):
                first = registry.record_gate("M0", output=output)
                second = registry.record_gate("M0", output=output)

            self.assertEqual(first, second)
            stored = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(len(stored), 1)


if __name__ == "__main__":
    unittest.main()
