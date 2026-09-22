from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "register_acceptance_evidence.py"
SPEC = importlib.util.spec_from_file_location("acceptance_registry", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class TestAcceptanceEvidenceRegistry(unittest.TestCase):
    def test_build_record_requires_pass_and_exact_head(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / "m0.json"
            artifact.write_text(json.dumps({"gate": "M0", "status": "PASS", "commit": "abc123"}), encoding="utf-8")
            payload = json.loads(artifact.read_text(encoding="utf-8"))
            with patch.object(MODULE, "_controller_version", return_value="1.2.3"):
                record = MODULE.build_record(
                    artifact, payload, code_head="", run_id="run-1", task_id="task-1", provider="chatgpt"
                )
            self.assertEqual(record["gate"], "M0")
            self.assertEqual(record["code_head"], "abc123")
            self.assertEqual(record["controller_version"], "1.2.3")
            self.assertEqual(record["identity"], {"run_id": "run-1", "task_id": "task-1"})
            self.assertEqual(record["provider"], "chatgpt")
            self.assertTrue(record["artifact_sha256"])

    def test_register_is_append_only_and_deduplicates_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry = Path(tmp) / "registry.jsonl"
            record = {"artifact_sha256": "deadbeef", "gate": "M1", "status": "PASS"}
            self.assertTrue(MODULE.register(record, registry))
            self.assertFalse(MODULE.register(record, registry))
            lines = registry.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            self.assertEqual(json.loads(lines[0])["artifact_sha256"], "deadbeef")

    def test_environment_fields_use_runner_context_without_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / "m2.json"
            artifact.write_text(json.dumps({"gate": "M2", "status": "PASS", "code_head": "feedface"}), encoding="utf-8")
            payload = json.loads(artifact.read_text(encoding="utf-8"))
            env = {"RUNNER_NAME": "pasi-wsl-1", "RUNNER_LABELS": "self-hosted,linux,x64,pasi-wsl"}
            with patch.dict(os.environ, env, clear=False), patch.object(MODULE, "_controller_version", return_value="9.9.9"):
                record = MODULE.build_record(artifact, payload, code_head="", run_id="", task_id="", provider="")
            self.assertEqual(record["environment"]["runner_name"], "pasi-wsl-1")
            self.assertIn("pasi-wsl", record["environment"]["runner_labels"])
            self.assertNotIn("PASI_BRIDGE_TOKEN", json.dumps(record))


if __name__ == "__main__":
    unittest.main()
