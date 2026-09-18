from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TestPasiCIWorkflow(unittest.TestCase):
    def test_pasi_branches_run_validation_on_push_and_pull_requests(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
        self.assertIn("branches: [main, beta-foundation, 'pasi/**']", workflow)
        self.assertIn("pull_request:\n    branches: [main, 'pasi/**']", workflow)

    def test_canonical_validation_is_present(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
        self.assertIn("bash scripts/check_all.sh", workflow)
        self.assertIn("Run targeted computer-use regression suites", workflow)


if __name__ == "__main__":
    unittest.main()
