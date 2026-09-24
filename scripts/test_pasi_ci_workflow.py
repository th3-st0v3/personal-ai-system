from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TestPasiCIWorkflow(unittest.TestCase):
    def test_pasi_branches_run_authoritative_validation_on_push(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
        self.assertIn("branches: [main, beta-foundation, 'pasi/**']", workflow)
        self.assertNotIn("pull_request:", workflow)
        self.assertIn("untrusted fork pull requests", workflow)

    def test_fast_validation_is_authoritative_and_live_acceptance_is_manual(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
        self.assertIn("runs-on: ubuntu-latest", workflow)
        self.assertIn("bash scripts/check_fast.sh", workflow)
        self.assertIn("mode:", workflow)
        self.assertIn("fast", workflow)
        self.assertIn("live", workflow)
        self.assertIn("scripts/e2e_chromium_response_recovery.py", workflow)
        self.assertIn("scripts/e2e_chromium_prompt_submission.py", workflow)
        self.assertNotIn("[self-hosted, linux, x64, pasi-wsl]", workflow)

    def test_authoritative_fast_lane_does_not_duplicate_the_full_quality_sweep(self) -> None:
        script = (ROOT / "scripts" / "check_fast.sh").read_text(encoding="utf-8")
        self.assertNotIn("check_all.sh", script)
        self.assertNotIn("apt-get", script)
        self.assertNotIn("e2e_chromium", script)


if __name__ == "__main__":
    unittest.main()
