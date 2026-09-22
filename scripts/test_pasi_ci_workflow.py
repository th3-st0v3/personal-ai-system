from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TestPasiCIWorkflow(unittest.TestCase):
    def test_pasi_branches_run_one_authoritative_validation_on_push(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
        self.assertIn("  push:\n", workflow)
        self.assertNotIn("  pull_request:", workflow)
        self.assertIn("runs-on: [self-hosted, linux, x64, pasi-wsl]", workflow)
        self.assertNotIn("runs-on: ubuntu-latest", workflow)

    def test_canonical_validation_is_present(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
        self.assertIn("bash scripts/check_all.sh", workflow)
        self.assertIn("Run targeted computer-use regression suites", workflow)

    def test_runner_capabilities_has_detect_only_scheduled_health(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "pasi-runner-capabilities.yml").read_text(encoding="utf-8")
        self.assertIn("  schedule:\n", workflow)
        self.assertIn("if: github.event_name == 'schedule'", workflow)
        health = workflow[workflow.index("  health:"):workflow.index("  reconcile:")]
        self.assertNotIn("--apply", health)
        self.assertNotIn("--apply-optional", health)
        self.assertIn("runs-on: [self-hosted, linux, x64, pasi-desktop]", health)

    def test_runner_capability_repair_is_manual_only(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "pasi-runner-capabilities.yml").read_text(encoding="utf-8")
        reconcile = workflow[workflow.index("  reconcile:"): ]
        self.assertIn("if: github.event_name == 'workflow_dispatch'", reconcile)
        self.assertIn('if [[ "$APPLY" == "true" ]]', reconcile)
        self.assertIn('if [[ "$APPLY_OPTIONAL" == "true" ]]', reconcile)

    def test_security_workflow_adds_pull_request_dependency_review(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "pasi-security-analysis.yml").read_text(encoding="utf-8")
        self.assertIn("  dependency-review:", workflow)
        self.assertIn("if: github.event_name == 'pull_request'", workflow)
        self.assertIn("uses: actions/dependency-review-action@v4", workflow)
        self.assertIn("fail-on-severity: high", workflow)
        dependency_job = workflow[workflow.index("  dependency-review:"):workflow.index("  secret-scan:")]
        self.assertIn("runs-on: [self-hosted, linux, x64, pasi-wsl]", dependency_job)

    def test_authoritative_workflows_have_no_hosted_runner_assignments(self) -> None:
        for path in (ROOT / ".github" / "workflows").glob("*.yml"):
            workflow = path.read_text(encoding="utf-8")
            self.assertNotIn("runs-on: ubuntu-", workflow, msg=str(path))


if __name__ == "__main__":
    unittest.main()
