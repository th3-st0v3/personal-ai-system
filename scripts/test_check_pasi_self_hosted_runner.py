from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.check_pasi_self_hosted_runner import inspect_runner


class TestSelfHostedRunnerPreflight(unittest.TestCase):
    def test_accepts_expected_github_self_hosted_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".runner").write_text("configured", encoding="utf-8")
            env = {
                "RUNNER_ENVIRONMENT": "self-hosted",
                "RUNNER_NAME": "pasi-wsl-runner",
                "RUNNER_OS": "Linux",
                "RUNNER_ARCH": "X64",
            }
            payload = inspect_runner(env, root)
        self.assertTrue(payload["ok"], payload)

    def test_rejects_github_hosted_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".runner").write_text("configured", encoding="utf-8")
            env = {
                "RUNNER_ENVIRONMENT": "github-hosted",
                "RUNNER_NAME": "Hosted Agent",
                "RUNNER_OS": "Linux",
                "RUNNER_ARCH": "X64",
            }
            payload = inspect_runner(env, root)
        self.assertFalse(payload["ok"])
        self.assertIn("RUNNER_ENVIRONMENT='github-hosted'", payload["problems"])

    def test_local_mode_requires_runner_listener_and_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            env = {}
            with patch(
                "scripts.check_pasi_self_hosted_runner.listener_ancestor_present",
                return_value=False,
            ):
                payload = inspect_runner(env, root)
        self.assertFalse(payload["ok"])
        self.assertTrue(any("runner configuration missing" in item for item in payload["problems"]))
        self.assertTrue(any("runner listener" in item for item in payload["problems"]))


if __name__ == "__main__":
    unittest.main()
