from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "pasi-quality-proofing.yml"


def job_block(source: str, job_name: str) -> str:
    pattern = re.compile(
        rf"(?ms)^  {re.escape(job_name)}:\n.*?(?=^  [A-Za-z0-9_-]+:|\Z)"
    )
    match = pattern.search(source)
    if not match:
        raise AssertionError(f"workflow job not found: {job_name}")
    return match.group(0)


class TestQualityProofingWorkflow(unittest.TestCase):
    def test_all_quality_jobs_are_self_hosted(self) -> None:
        source = WORKFLOW.read_text(encoding="utf-8")
        selectors = re.findall(r"(?m)^\s*runs-on:\s*(.+)$", source)
        self.assertEqual(
            selectors,
            [
                "[self-hosted, linux, x64, pasi-wsl]",
                "[self-hosted, linux, x64, pasi-wsl]",
                "[self-hosted, linux, x64, pasi-wsl]",
            ],
        )
        self.assertNotIn("ubuntu-latest", source)

    def test_local_proofing_runs_the_shared_local_contract(self) -> None:
        job = job_block(WORKFLOW.read_text(encoding="utf-8"), "local-proofing")
        self.assertIn("python -m pip install -r requirements-dev.txt", job)
        self.assertIn("pre-commit run --all-files", job)
        self.assertIn("python scripts/pasi_local_proof.py --all", job)
        self.assertIn("python scripts/check_pasi_self_hosted_runner.py", job)

    def test_local_proofing_has_self_hosted_runner_preflight(self) -> None:
        job = job_block(WORKFLOW.read_text(encoding="utf-8"), "local-proofing")
        self.assertIn("pasi-wsl", job)
        self.assertIn("scripts/check_pasi_self_hosted_runner.py", job)

    def test_coverage_stage_is_separate_and_archived(self) -> None:
        source = WORKFLOW.read_text(encoding="utf-8")
        job = job_block(source, "coverage")
        self.assertIn("needs: local-proofing", job)
        self.assertIn("scripts/run_python_coverage.py", job)
        self.assertIn("actions/upload-artifact@v7", job)
        self.assertIn("pasi-python-coverage", job)

    def test_post_merge_smoke_is_main_branch_only_and_after_coverage(self) -> None:
        source = WORKFLOW.read_text(encoding="utf-8")
        job = job_block(source, "post-merge-smoke")
        self.assertIn("needs: coverage", job)
        self.assertIn("github.event_name == 'push' && github.ref_name == 'main'", job)
        self.assertIn("scripts/ci_web_smoke.py", job)

    def test_quality_workflow_does_not_duplicate_security_pipeline(self) -> None:
        source = WORKFLOW.read_text(encoding="utf-8")
        self.assertNotIn("codeql-action/", source)
        self.assertNotIn("pip-audit", source)
        self.assertNotIn("scan_repository_secrets.py", source)
