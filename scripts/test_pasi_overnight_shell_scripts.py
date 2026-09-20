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
    def test_operator_shell_scripts_pass_bash_syntax(self) -> None:
        for script in SCRIPTS:
            self.assertTrue(script.is_file(), script)
            result = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_168h_launcher_contains_isolation_and_service_guards(self) -> None:
        script = (ROOT / "scripts" / "start_pasi_168h.sh").read_text(encoding="utf-8")
        for required in (
            'export PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}"',
            'WORKTREE="$HOME/.pasi-worktrees/personal-ai-system-overnight-',
            'BRANCH="${PASI_OVERNIGHT_BRANCH:-pasi/overnight-',
            '--worktree "$WORKTREE"',
            '--branch "$BRANCH"',
            'START_PID_FILE="$RUNTIME_DIR/start.pid"',
            'printf \'%s\\n\' "$$" > "$START_PID_FILE"',
            '[[ "$(cat "$START_PID_FILE" 2>/dev/null || true)" == "$$" ]]',
            'http://127.0.0.1:8765/health',
            'http://127.0.0.1:8766/health',
            'automation.orchestrator.bridge',
            'pasi_controller_server.py',
            'BRIDGE_PID_FILE="$RUNTIME_DIR/bridge.pid"',
            'CONTROLLER_PID_FILE="$RUNTIME_DIR/controller-distribution.pid"',
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
        self.assertIn("controller-distribution.pid", stop_script)
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
            'EXTENSION_TOKEN_FILE="$REPO_ROOT/automation/chromium/pasi-chatgpt/.bridge-token"',
            'secrets.token_urlsafe(48)',
            'export PASI_BRIDGE_TOKEN="$(cat "$TOKEN_FILE")"',
            'Authorization": f"Bearer {token}',
            'chmod 600 "$TOKEN_FILE"',
            'chmod 600 "$EXTENSION_TOKEN_FILE"',
        ):
            self.assertIn(required, script)

    def test_168h_launcher_verifies_detached_runner_startup(self) -> None:
        script = (ROOT / "scripts" / "start_pasi_168h.sh").read_text(encoding="utf-8")
        self.assertIn("runner_start_deadline=$((SECONDS + 15))", script)
        self.assertIn("runner_ready=0", script)
        self.assertIn('kill -0 "$runner_pid"', script)
        self.assertIn("detached PASI runner did not become live", script)

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
