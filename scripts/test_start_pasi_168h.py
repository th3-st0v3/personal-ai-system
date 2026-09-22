from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class TestPasi168HourLauncherContract(unittest.TestCase):
    def setUp(self) -> None:
        self.source = (ROOT / "scripts" / "start_pasi_168h.sh").read_text(encoding="utf-8")

    def test_launcher_supports_host_service_foreground_mode(self) -> None:
        self.assertIn("foreground_supervisor=0", self.source)
        self.assertIn("--foreground-supervisor", self.source)
        self.assertIn("if (( foreground_supervisor == 1 )); then", self.source)
        self.assertIn('wait "$pid"', self.source)

    def test_launcher_verifies_native_browser_before_detaching_runner(self) -> None:
        preflight = self.source.index("=== VERIFYING NATIVE CHATGPT BROWSER ===")
        runner = self.source.index("$REPO_ROOT/scripts/pasi_168h_supervisor.sh", preflight)
        self.assertLess(preflight, runner)
        self.assertIn("http://127.0.0.1:8765/browser/health", self.source)
        self.assertIn('controller_source_path = root / "automation" / "chromium" / "pasi-chatgpt" / "content.js"', self.source)
        self.assertNotIn('manifest_path = root / "automation" / "chromium" / "pasi-chatgpt" / "manifest.json"', self.source)
        self.assertNotIn("127.0.0.1:8766", self.source)
        self.assertNotIn("pasi_controller_server.py", self.source)
        self.assertIn('data.get("controller_version") != expected_version.strip()', self.source)
        self.assertIn('if data.get("native_controller") is not True:', self.source)
        self.assertIn("auth_required", self.source)
        self.assertIn("browser_deadline=$((SECONDS + 30))", self.source)
        self.assertIn("exit 8", self.source)
        self.assertIn("captured_at", self.source)
        self.assertIn('raw_capture = observation.get("captured_at") if isinstance(observation, dict) else None', self.source)
        self.assertIn('captured_at = raw_capture if isinstance(raw_capture, str) else None', self.source)
        self.assertIn("age_seconds > 30", self.source)
        self.assertIn("pasi_168h_supervisor.sh", self.source)

    def test_launcher_allows_supervisor_recovery_when_engine_outlives_supervisor(self) -> None:
        self.assertIn("is live without its supervisor; launching a supervisor to adopt the existing engine", self.source)
        self.assertIn('if [[ -f "$SUPERVISOR_PID_FILE" ]]; then', self.source)
    def test_launcher_recovers_live_runner_identity_before_supervisor_adoption(self) -> None:
        self.assertIn('STATE_FILE="$RUNTIME_DIR/state.json"', self.source)
        self.assertIn("adopt_existing_runner=0", self.source)
        self.assertIn('existing_runner_pid=""', self.source)
        self.assertIn('runner_command_line="$(ps -p "$pid" -o args= 2>/dev/null || true)"', self.source)
        self.assertIn('pasi_extended_runtime_entrypoint.py', self.source)
        self.assertIn('state_values="$("$PYTHON" - "$STATE_FILE"', self.source)
        self.assertIn('requested_branch="${requested_branch:-$state_branch}', self.source)
        self.assertIn('configured_worktree="${configured_worktree:-$state_worktree}', self.source)
        self.assertIn("refusing to risk a duplicate engine", self.source)
        self.assertIn("Adopting existing PASI runner identity", self.source)

    def test_launcher_does_not_report_started_when_browser_preflight_fails(self) -> None:
        failure = self.source.index("exit 8")
        started = self.source.index("Started PASI extended runner")
        self.assertLess(failure, started)


class TestBranchHygieneWorkflowContract(unittest.TestCase):
    def test_cleanup_run_is_not_cancelled_by_another_cleanup_trigger(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "branch-hygiene.yml").read_text(encoding="utf-8")
        self.assertIn("concurrency:", workflow)
        self.assertIn("cancel-in-progress: false", workflow)


if __name__ == "__main__":
    unittest.main()
