from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TestActionsRunnerLauncher(unittest.TestCase):
    def test_start_script_is_headless_and_idempotent(self) -> None:
        source = (ROOT / "scripts" / "start_pasi_actions_runner.sh").read_text(encoding="utf-8")
        self.assertIn("nohup ./run.sh", source)
        self.assertIn("runner.pid", source)
        self.assertIn("already active", source)
        self.assertIn("find_listener_pid", source)
        self.assertIn("PASI self-hosted runner started", source)
        self.assertIn("ACTIONS", source)

    def test_install_script_delegates_persistent_startup_to_shared_launcher(self) -> None:
        source = (ROOT / "scripts" / "install_pasi_self_hosted_runner.sh").read_text(encoding="utf-8")
        self.assertIn("start_pasi_actions_runner.sh", source)
        self.assertNotIn('nohup ./run.sh >>"$RUNNER_ROOT/runner.log"', source)

    def test_status_script_reports_ready_from_runner_pid(self) -> None:
        source = (ROOT / "scripts" / "status_pasi_actions_runner.sh").read_text(encoding="utf-8")
        self.assertIn("PASI_ACTIONS_RUNNER: READY", source)
        self.assertIn(".runner", source)
        self.assertIn("systemctl", source)
        self.assertIn("find_listener_pid", source)

    def test_scripts_have_valid_shell_syntax(self) -> None:
        for name in (
            "start_pasi_actions_runner.sh",
            "status_pasi_actions_runner.sh",
        ):
            subprocess.run(["bash", "-n", str(ROOT / "scripts" / name)], check=True)


if __name__ == "__main__":
    unittest.main()
