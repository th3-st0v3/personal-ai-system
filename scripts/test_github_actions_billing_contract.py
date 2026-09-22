from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEST_WORKFLOW = ROOT / ".github" / "workflows" / "test.yml"


class TestGitHubActionsBillingContract(unittest.TestCase):
    def test_required_free_validation_is_self_hosted(self) -> None:
        source = TEST_WORKFLOW.read_text(encoding="utf-8")
        job_start = source.index("  free-validation:")
        job_end = source.index("
  test:", job_start)
        job = source[job_start:job_end]

        self.assertIn(
            "runs-on: [self-hosted, linux, x64, pasi-wsl]",
            job,
        )
        self.assertNotIn("runs-on: ubuntu-latest", job)
        self.assertNotIn("runs-on: ubuntu-", job)
        self.assertIn("scripts/run_free_acceptance.py", job)

    def test_free_validation_job_does_not_require_billing_state(self) -> None:
        source = TEST_WORKFLOW.read_text(encoding="utf-8")
        job_start = source.index("  free-validation:")
        job_end = source.index("
  test:", job_start)
        job = source[job_start:job_end]
        self.assertNotIn("ubuntu-latest", job)
        self.assertNotIn("ubuntu-24.04", job)
        self.assertNotIn("ubuntu-22.04", job)


if __name__ == "__main__":
    unittest.main()
