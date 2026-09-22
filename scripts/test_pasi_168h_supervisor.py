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

    def test_supervisor_adopts_matching_live_engine_after_restart(self) -> None:
        self.assertIn("runner_cmd_matches()", self.source)
        self.assertIn("adopting already-running engine PID", self.source)
        self.assertIn("monitoring adopted engine PID", self.source)
        self.assertIn('[[ "$command_line" == *"pasi_extended_runtime_entrypoint.py"* ]]', self.source)
        self.assertIn('[[ "$command_line" == *"--worktree $worktree"* ]]', self.source)
        self.assertIn('[[ "$command_line" == *"--branch $branch"* ]]', self.source)

    def test_launcher_supports_a_persistent_self_hosted_python_environment(self) -> None:
        source = (ROOT / "scripts" / "start_pasi_168h.sh").read_text(encoding="utf-8")
        self.assertIn('PASI_VENV="${PASI_VENV:-$HOME/.pasi/venv}"', source)
        self.assertIn('PASI_PYTHON', source)
        self.assertIn('python3 -m venv "$PASI_VENV"', source)
        self.assertIn('pip install --disable-pip-version-check --requirement "$REPO_ROOT/requirements.txt"', source)
        self.assertIn('requirements-dev.txt', source)

    def test_supervisor_has_bounded_backoff_and_terminal_stop_controls(self) -> None:
        self.assertIn("PASI_SUPERVISOR_BACKOFF_SECONDS", self.source)
        self.assertIn("PASI_SUPERVISOR_MAX_BACKOFF_SECONDS", self.source)
        self.assertIn('sleep "$backoff"', self.source)
        self.assertIn('trap \'touch "$STOP_FILE"; exit 0\' INT TERM', self.source)
        self.assertIn("state_deadline_reached", self.source)
        self.assertIn("state_is_terminal", self.source)
        self.assertIn('"roadmap_complete"', self.source)
        self.assertIn('"roadmap_blocked_or_no_eligible_task"', self.source)

    def test_chromium_e2e_uses_process_group_cleanup(self) -> None:
        source = (ROOT / "scripts" / "e2e_chromium_response_recovery.py").read_text(encoding="utf-8")
        self.assertIn("start_new_session=True", source)
        self.assertIn("os.killpg(chrome_process.pid, signal.SIGTERM)", source)
        self.assertIn("signal.SIGKILL", source)

