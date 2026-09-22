from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TestPasi168HourDurableServiceContract(unittest.TestCase):
    def test_launcher_scripts_have_valid_shell_syntax(self) -> None:
        for relative_path in ("scripts/start_pasi_168h.sh", "scripts/start_pasi_168h_service.sh"):
            result = subprocess.run(["bash", "-n", str(ROOT / relative_path)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_service_launcher_uses_host_systemd_and_persistent_checkout(self) -> None:
        source = (ROOT / "scripts" / "start_pasi_168h_service.sh").read_text(encoding="utf-8")
        self.assertIn("systemd-run", source)
        self.assertIn("--user", source)
        self.assertIn("--collect", source)
        self.assertIn("--no-block", source)
        self.assertIn("SERVICE_PATH", source)
        self.assertIn('--setenv=PATH="$SERVICE_PATH"', source)
        self.assertIn("--unit=", source)
        self.assertIn("--property=KillMode=control-group", source)
        self.assertIn('--working-directory="$SERVICE_ROOT"', source)
        self.assertIn('SERVICE_ROOT="${PASI_OVERNIGHT_SERVICE_ROOT:-$HOME/.pasi/overnight-service/personal-ai-system}"', source)
        self.assertIn('bash "$SERVICE_ROOT/scripts/start_pasi_168h.sh" --foreground-supervisor', source)
        self.assertIn('git -C "$SERVICE_ROOT" fetch --no-tags origin "$REF"', source)
        self.assertIn('REQUESTED_ROADMAP="${PASI_ROADMAP_PATH:-roadmaps/pasi-default.json}"', source)
        self.assertIn('--setenv=PASI_ROADMAP_PATH="$REQUESTED_ROADMAP"', source)
        self.assertIn('PLANNER_MODEL="${PASI_PLANNER_MODEL:-}"', source)
        self.assertIn('PLANNER_AI_RANK="${PASI_PLANNER_AI_RANK:-}"', source)
        self.assertIn('--setenv=PASI_PLANNER_MODEL="$PLANNER_MODEL"', source)
        self.assertIn('--setenv=PASI_PLANNER_AI_RANK="$PLANNER_AI_RANK"', source)
        self.assertIn("refusing to reset potentially unpushed work", source)
        self.assertIn("PASI 168-hour service verified live", source)
        self.assertIn("service_identity_matches", source)
        self.assertIn("service_processes_are_live", source)
        self.assertIn("no live supervisor/runner PIDs", source)
        self.assertIn('refusing to treat stale state as healthy', source)
        self.assertIn("different branch or roadmap", source)
        self.assertIn("START_LOCK_FILE", source)

    def test_service_launcher_does_not_depend_on_actions_job_lifetime(self) -> None:
        source = (ROOT / "scripts" / "start_pasi_168h_service.sh").read_text(encoding="utf-8")
        self.assertNotIn("nohup", source)
        self.assertNotIn("disown", source)

    def test_desktop_gate_hands_off_to_durable_service(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "pasi-desktop-gate.yml").read_text(encoding="utf-8")
        self.assertIn("bash scripts/start_pasi_168h_service.sh", workflow)
        self.assertNotIn("bash scripts/start_pasi_168h.sh", workflow)


if __name__ == "__main__":
    unittest.main()
