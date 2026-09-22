from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class TestPasi168HourLauncherContract(unittest.TestCase):
    def setUp(self) -> None:
        self.source = (ROOT / "scripts" / "start_pasi_168h.sh").read_text(encoding="utf-8")

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

    def test_branch_hygiene_covers_all_branch_lifecycle_triggers(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "branch-hygiene.yml").read_text(encoding="utf-8")
        self.assertIn("  push:", workflow)
        self.assertIn("  pull_request:", workflow)
        self.assertIn("types: [opened, synchronize, closed, converted_to_ready_for_review]", workflow)
        self.assertIn("  workflow_run:", workflow)
        self.assertIn('workflows: ["test"]', workflow)
        self.assertIn("  schedule:", workflow)
        self.assertIn("  workflow_dispatch:", workflow)

    def test_branch_hygiene_uses_only_self_hosted_execution(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "branch-hygiene.yml").read_text(encoding="utf-8")
        self.assertIn("runs-on: [self-hosted, linux, x64, pasi-wsl]", workflow)
        self.assertNotIn("ubuntu-latest", workflow)

    def test_authoritative_test_workflow_runs_on_all_branches_and_self_hosted(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
        self.assertIn("  push:\n  pull_request:\n", workflow)
        self.assertNotIn("branches: [main, beta-foundation, 'pasi/**']", workflow)
        self.assertNotIn("runs-on: ubuntu-latest", workflow)
        self.assertIn("runs-on: [self-hosted, linux, x64, pasi-wsl]", workflow)

    def test_security_workflow_does_not_request_github_hosted_runners(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "pasi-security-analysis.yml").read_text(encoding="utf-8")
        self.assertNotIn("ubuntu-latest", workflow)
        self.assertIn("self-hosted", workflow)

    def test_branch_hygiene_has_write_permissions_for_pr_reconciliation(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "branch-hygiene.yml").read_text(encoding="utf-8")
        self.assertIn("contents: write", workflow)
        self.assertIn("pull-requests: write", workflow)
        self.assertIn("scripts/reconcile_branch_prs.py --json", workflow)

    def test_branch_hygiene_reconciler_uses_canonical_controller_ref(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "branch-hygiene.yml").read_text(encoding="utf-8")
        self.assertIn("          ref: main", workflow)

    def test_branch_hygiene_protects_fork_pull_requests(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "branch-hygiene.yml").read_text(encoding="utf-8")
        self.assertIn("github.event.pull_request.head.repo.full_name == github.repository", workflow)



if __name__ == "__main__":
    unittest.main()
