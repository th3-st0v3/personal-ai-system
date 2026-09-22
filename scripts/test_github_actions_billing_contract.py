from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEST_WORKFLOW = ROOT / ".github" / "workflows" / "test.yml"
WORKFLOW_DIR = ROOT / ".github" / "workflows"


def job_block(source: str, job_name: str) -> str:
    pattern = re.compile(
        rf"(?ms)^  {re.escape(job_name)}:\n.*?(?=^  [A-Za-z0-9_-]+:|\Z)"
    )
    match = pattern.search(source)
    if not match:
        raise AssertionError(f"workflow job not found: {job_name}")
    return match.group(0)




RUNNER_SELECTOR_PATTERN = re.compile(
    r"runs-on: \$\{\{ inputs\.runner_mode == '([^']+)' "
    r"&& '([^']+)' \|\| '([^']+)' \}\}"
)


def runner_mapping_from_workflow(source: str) -> tuple[str, str, str]:
    matches = RUNNER_SELECTOR_PATTERN.findall(source)
    if not matches:
        raise AssertionError("runner_mode runs-on expression not found")
    unique = list(dict.fromkeys(matches))
    if len(unique) != 1:
        raise AssertionError(f"expected one consistent runner mapping, found {unique}")
    return unique[0]


class TestGitHubActionsBillingContract(unittest.TestCase):
    def test_test_workflow_defaults_every_test_job_to_self_hosted(self) -> None:
        source = TEST_WORKFLOW.read_text(encoding="utf-8")
        expected_selector = (
            "runs-on: ${{ inputs.runner_mode == 'github-hosted' "
            "&& 'ubuntu-latest' || 'pasi-wsl' }}"
        )
        for job_name in ("runner-preflight", "free-validation", "test", "browser-use-compat"):
            job = job_block(source, job_name)
            self.assertIn(expected_selector, job, job_name)
        self.assertNotIn("runs-on: ubuntu-", source)

    def test_manual_runner_switch_is_explicit_and_self_hosted_by_default(self) -> None:
        source = TEST_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("runner_mode:", source)
        self.assertIn("default: self-hosted", source)
        self.assertRegex(
            source,
            r"options:\n\s+- self-hosted\n\s+- github-hosted",
        )
        self.assertIn("actions/checkout@v7", source)

    def test_runner_mode_maps_exactly_to_each_runner(self) -> None:
        source = TEST_WORKFLOW.read_text(encoding="utf-8")
        condition_value, github_runner, default_runner = runner_mapping_from_workflow(source)

        self.assertEqual(condition_value, "github-hosted")
        self.assertEqual(github_runner, "ubuntu-latest")
        self.assertEqual(default_runner, "pasi-wsl")

        def resolve(mode: str) -> str:
            return github_runner if mode == condition_value else default_runner

        self.assertEqual(resolve("github-hosted"), "ubuntu-latest")
        self.assertEqual(resolve("self-hosted"), "pasi-wsl")

    def test_self_hosted_preflight_is_part_of_required_test_gate(self) -> None:
        source = TEST_WORKFLOW.read_text(encoding="utf-8")
        preflight = job_block(source, "runner-preflight")
        self.assertIn("pasi-wsl", preflight)
        self.assertIn("scripts/check_pasi_self_hosted_runner.py", preflight)
        for job_name in ("free-validation", "test", "browser-use-compat"):
            self.assertIn("needs: runner-preflight", job_block(source, job_name))

    def test_self_hosted_only_prerequisite_checks_do_not_block_hosted_mode(self) -> None:
        source = TEST_WORKFLOW.read_text(encoding="utf-8")
        for step_name in (
            "Validate validation sandbox",
            "Validate browser acceptance prerequisites",
        ):
            marker = "      - name: " + step_name + "\n"
            start = source.index(marker)
            if_pos = source.index("        if: ", start)
            end = source.index("\n", if_pos)
            condition = source[if_pos:end]
            self.assertIn("inputs.runner_mode != 'github-hosted'", condition)

    def test_required_free_validation_stays_local_and_free(self) -> None:
        source = TEST_WORKFLOW.read_text(encoding="utf-8")
        job = job_block(source, "free-validation")
        self.assertIn("scripts/run_free_acceptance.py", job)
        self.assertNotIn("ubuntu-24.04", job)
        self.assertNotIn("ubuntu-22.04", job)
        self.assertIn("PASI_FREE_TEST_MODE: '1'", job)

    def test_no_static_github_hosted_runner_selector_exists_in_workflows(self) -> None:
        for path in WORKFLOW_DIR.glob("*.yml"):
            source = path.read_text(encoding="utf-8")
            self.assertNotRegex(
                source,
                r"(?m)^\s*runs-on:\s*ubuntu-[^\s]+\s*$",
                msg=f"static GitHub-hosted runner selector in {path}",
            )


if __name__ == "__main__":
    unittest.main()
