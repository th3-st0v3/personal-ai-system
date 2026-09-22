from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TestPasiCIWorkflow(unittest.TestCase):
    def test_pasi_branches_run_validation_on_push_and_pull_requests(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
        self.assertIn("branches: [main, beta-foundation, 'pasi/**']", workflow)
        self.assertIn("pull_request:\n    branches: [main, 'pasi/**']", workflow)
        self.assertIn("runs-on: [self-hosted, linux, x64, pasi-wsl]", workflow)
        self.assertIn("github.event.pull_request.head.repo.full_name == github.repository", workflow)

    def test_168h_desktop_gate_hands_off_to_host_service_manager(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "pasi-desktop-gate.yml").read_text(encoding="utf-8")
        self.assertIn("bash scripts/start_pasi_168h_service.sh", workflow)
        self.assertNotIn("bash scripts/start_pasi_168h.sh", workflow)

    def test_canonical_validation_is_present(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
        self.assertIn("bash scripts/check_all.sh", workflow)
        self.assertIn("Run targeted computer-use regression suites", workflow)


    def test_pull_requests_use_fast_changed_file_gate_and_keep_full_gate_for_main(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
        self.assertIn("Run changed-file fast validation", workflow)
        self.assertIn("scripts/pasi_fast_validation.py", workflow)
        self.assertIn("run: bash scripts/check_all.sh", workflow)
        self.assertIn("browser-use-compat:", workflow)
        self.assertIn("fetch-depth: 1", workflow)

    def test_full_suite_runs_on_schedule_and_codeql_keeps_security_write_permission(self) -> None:
        test_workflow = (ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
        self.assertIn("schedule:", test_workflow)
        self.assertIn("- cron: '30 4 * * *'", test_workflow)
        self.assertIn("github.event_name == 'schedule'", test_workflow)
        security = (ROOT / ".github" / "workflows" / "pasi-security-analysis.yml").read_text(encoding="utf-8")
        self.assertIn("security-events: write", security)
        self.assertIn("upload: never", security)

if __name__ == "__main__":
    unittest.main()
