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
            'http://127.0.0.1:8765/health',
            'http://127.0.0.1:8766/health',
            'automation.orchestrator.bridge',
            'pasi_controller_server.py',
        ):
            self.assertIn(required, script)

    def test_launchers_do_not_leak_start_lock_to_detached_children(self) -> None:
        for name in ("start_pasi_overnight.sh", "start_pasi_168h.sh"):
            script = (ROOT / "scripts" / name).read_text(encoding="utf-8")
            self.assertIn("exec 9>&-", script)
            self.assertIn("nohup bash -c", script)


if __name__ == "__main__":
    unittest.main()
