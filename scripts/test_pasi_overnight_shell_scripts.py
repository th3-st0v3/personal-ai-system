from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = (
    ROOT / "scripts" / "start_pasi_overnight.sh",
    ROOT / "scripts" / "start_pasi_168h.sh",
    ROOT / "scripts" / "stop_pasi_overnight.sh",
    ROOT / "scripts" / "status_pasi_overnight.sh",
)


class TestPasiOvernightShellScripts(unittest.TestCase):
    def test_check_all_uses_grouped_directory_pruning_for_file_discovery(self) -> None:
        script = (ROOT / "scripts" / "check_all.sh").read_text(encoding="utf-8")
        self.assertIn("find_expr=(find .)", script)
        self.assertIn('for dir in "${pruned_dirs[@]}"; do', script)
        self.assertIn('find_expr+=( -type d -name "${dir#./}" -prune -o )', script)
        self.assertIn("find_expr+=( -type f )", script)
        self.assertIn("./node_modules", script)
        self.assertIn("./.runtime", script)

    def test_check_all_discovers_and_runs_supported_javascript_suites(self) -> None:
        script = (ROOT / "scripts" / "check_all.sh").read_text(encoding="utf-8")
        for required in (
            "JAVASCRIPT_TEST_FILES",
            "-name 'test_*.js'",
            "-name '*.test.js'",
            "-name '*.spec.js'",
            "node --test",
            "JavaScript syntax (non-test files)",
            "JAVASCRIPT_TEST_SET",
            "JavaScript test suites",
        ):
            self.assertIn(required, script)
        self.assertIn("test_*.mjs", script)
        self.assertIn("test_*.cjs", script)

    def test_operator_shell_scripts_pass_bash_syntax(self) -> None:
        for script in SCRIPTS:
            self.assertTrue(script.is_file(), script)
            result = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_168h_launcher_reuses_requested_branch_worktree_and_syncs_remote(self) -> None:
        script = (ROOT / "scripts" / "start_pasi_168h.sh").read_text(encoding="utf-8")
        for required in (
            "worktree_for_branch",
            "REUSE_EXISTING_WORKTREE=0",
            "git worktree list --porcelain",
            "git -C \"$WORKTREE\" branch --show-current",
            "git -C \"$WORKTREE\" status --porcelain --untracked-files=all",
            "git -C \"$WORKTREE\" merge --ff-only \"origin/$BRANCH\"",
            "has diverged from origin",
            "PASI_OVERNIGHT_BASE_REF",
        ):
            self.assertIn(required, script)

    def test_168h_launcher_contains_isolation_and_native_service_guards(self) -> None:
        script = (ROOT / "scripts" / "start_pasi_168h.sh").read_text(encoding="utf-8")
        for required in (
            'export PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}"',
            'WORKTREE="$HOME/.pasi-worktrees/personal-ai-system-overnight-',
            'requested_branch="${PASI_OVERNIGHT_BRANCH:-}"',
            '--worktree "$WORKTREE"',
            '--branch "$BRANCH"',
            'START_PID_FILE="$RUNTIME_DIR/start.pid"',
            'printf \'%s\\n\' "$$" > "$START_PID_FILE"',
            '[[ "$(cat "$START_PID_FILE" 2>/dev/null || true)" == "$$" ]]',
            'http://127.0.0.1:8765/health',
            'http://127.0.0.1:8765/browser/health',
            'automation.orchestrator.bridge',
            'BRIDGE_PID_FILE="$RUNTIME_DIR/bridge.pid"',
        ):
            self.assertIn(required, script)

    def test_startup_launcher_tracks_start_pid_for_recovery(self) -> None:
        for name in ("start_pasi_overnight.sh", "start_pasi_168h.sh"):
            script = (ROOT / "scripts" / name).read_text(encoding="utf-8")
            self.assertIn("start.pid", script)
            self.assertIn("cleanup_start_pid", script)

        stop_script = (ROOT / "scripts" / "stop_pasi_overnight.sh").read_text(encoding="utf-8")
        self.assertIn("stop_managed_service", stop_script)
        self.assertIn("bridge.pid", stop_script)
        self.assertNotIn("controller-distribution.pid", stop_script)
        self.assertNotIn("pasi_controller_server.py", stop_script)
        self.assertNotIn("PASI controller distribution", stop_script)
        self.assertIn("START_PID_FILE", stop_script)
        self.assertIn("start_pasi_168h.sh", stop_script)

        status_script = (ROOT / "scripts" / "status_pasi_overnight.sh").read_text(encoding="utf-8")
        self.assertIn("Startup launcher: ACTIVE", status_script)
        self.assertIn("Managed services:", status_script)
        self.assertIn("MANAGED (PID", status_script)

    def test_168h_launcher_provisions_managed_bridge_token(self) -> None:
        script = (ROOT / "scripts" / "start_pasi_168h.sh").read_text(encoding="utf-8")
        for required in (
            'TOKEN_FILE="$HOME/.pasi/bridge-token"',
            'EXTENSION_SOURCE_TOKEN_FILE="$REPO_ROOT/automation/chromium/pasi-chatgpt/.bridge-token"',
            'EXTENSION_BUNDLE_DIR="${PASI_BROWSER_EXTENSION_DIR:-$REPO_ROOT/.runtime/chromium/pasi-chatgpt}"',
            'EXTENSION_TOKEN_FILE="$EXTENSION_BUNDLE_DIR/.bridge-token"',
            'cp "$TOKEN_FILE" "$EXTENSION_TOKEN_FILE"',
            'secrets.token_urlsafe(48)',
            'export PASI_BRIDGE_TOKEN="$(cat "$TOKEN_FILE")"',
            'Authorization": f"Bearer {token}',
            'chmod 600 "$TOKEN_FILE"',
            'chmod 600 "$EXTENSION_TOKEN_FILE"',
        ):
            self.assertIn(required, script)

    def test_168h_launcher_surfaces_detached_runner_failure_log(self) -> None:
        script = (ROOT / "scripts" / "start_pasi_168h.sh").read_text(encoding="utf-8")
        self.assertIn('tail -80 "$log_file"', script)
        self.assertIn('kill "$pid"', script)

    def test_168h_launcher_verifies_detached_runner_startup(self) -> None:
        script = (ROOT / "scripts" / "start_pasi_168h.sh").read_text(encoding="utf-8")
        self.assertIn("runner_start_deadline=$((SECONDS + ${PASI_STARTUP_VERIFY_SECONDS:-90}))", script)
        self.assertIn("runner_ready=0", script)
        self.assertIn('kill -0 "$runner_pid"', script)
        self.assertIn("detached PASI supervisor/runner did not become live", script)

    def test_overnight_launcher_verifies_detached_runner_startup(self) -> None:
        script = (ROOT / "scripts" / "start_pasi_overnight.sh").read_text(encoding="utf-8")
        self.assertIn("runner_start_deadline=$((SECONDS + 15))", script)
        self.assertIn("runner_ready=0", script)
        self.assertIn('kill -0 "$runner_pid"', script)
        self.assertIn("detached PASI runner did not become live", script)

    def test_launchers_do_not_leak_start_lock_to_detached_children(self) -> None:
        for name in ("start_pasi_overnight.sh", "start_pasi_168h.sh"):
            script = (ROOT / "scripts" / name).read_text(encoding="utf-8")
            self.assertIn("exec 9>&-", script)
            self.assertIn("nohup bash -c", script)

    @unittest.skipUnless(Path("/proc").is_dir(), "Linux /proc is required for fd inheritance regression")
    def test_lock_closing_wrapper_really_closes_fd_9(self) -> None:
        lock_path = ROOT / ".runtime" / "overnight" / "test-start.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("w") as lock:
            import os

            os.set_inheritable(lock.fileno(), True)
            result = subprocess.run(
                [
                    "bash",
                    "-c",
                    'exec 9>&3; exec 3>&-; nohup bash -c \'exec 9>&-; exec "$@"\' _ sleep 2 >/dev/null 2>&1 & echo $!',
                ],
                pass_fds=(lock.fileno(),),
                capture_output=True,
                text=True,
                check=True,
            )
            child_pid = int(result.stdout.strip())
            fd_path = Path("/proc") / str(child_pid) / "fd" / "9"
            self.assertFalse(fd_path.exists())
            subprocess.run(["kill", str(child_pid)], check=False)


if __name__ == "__main__":
    unittest.main()
