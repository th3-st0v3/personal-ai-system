from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class TestPasi168HourSupervisorContract(unittest.TestCase):
    def setUp(self) -> None:
        self.source = (ROOT / "scripts" / "pasi_168h_supervisor.sh").read_text(encoding="utf-8")

    def test_supervisor_is_fixed_to_168_hours_and_requires_isolated_run_identity(self) -> None:
        self.assertIn('hours="168"', self.source)
        self.assertIn('[[ "$hours" == "168" || "$hours" == "168.0" ]]', self.source)
        self.assertIn("--worktree", self.source)
        self.assertIn("--branch", self.source)
        self.assertIn("pasi_extended_runtime_entrypoint.py", self.source)

    def test_supervisor_resumes_after_unexpected_engine_exit(self) -> None:
        self.assertIn("resume=0", self.source)
        self.assertIn("cmd+=(--resume)", self.source)
        self.assertIn("resume=1", self.source)
        self.assertIn("engine exited code=$code", self.source)
        self.assertIn("PASI_SUPERVISOR_MAX_RESTARTS", self.source)
        self.assertIn("restart budget exhausted", self.source)

    def test_supervisor_has_bounded_backoff_and_terminal_stop_controls(self) -> None:
        self.assertIn("PASI_SUPERVISOR_BACKOFF_SECONDS", self.source)
        self.assertIn("PASI_SUPERVISOR_MAX_BACKOFF_SECONDS", self.source)
        self.assertIn('sleep "$backoff"', self.source)
        self.assertIn('trap \'touch "$STOP_FILE"; exit 0\' INT TERM', self.source)
        self.assertIn("state_deadline_reached", self.source)
        self.assertIn("state_is_terminal", self.source)

if __name__ == "__main__":
    unittest.main()
