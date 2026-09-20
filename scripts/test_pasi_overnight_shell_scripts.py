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
        self.assertIn("for dir in \"${pruned_dirs[@]}\"; do", script)
        self.assertIn("find_expr+=( -type f )", script)
        self.assertIn("-name 'node_modules'", script)
        self.assertIn("-name '.runtime'", script)

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