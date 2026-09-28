from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import reconcile_runner_capabilities as capabilities


class RunnerCapabilitiesTests(unittest.TestCase):
    def test_spec_loads_satellite_boundary(self) -> None:
        spec = capabilities.load_spec(Path("config/runner/capabilities.json"))
        self.assertEqual(spec["schema_version"], 1)
        self.assertEqual(spec["resource_boundary"]["max_memory_mib"], 3072)
        self.assertEqual(spec["resource_boundary"]["max_cpu_count"], 2)
        self.assertEqual(spec["resource_boundary"]["max_swap_mib"], 0)

    def test_detect_marks_missing_command(self) -> None:
        spec = {
            "schema_version": 1,
            "resource_boundary": {"max_memory_mib": 999999, "max_cpu_count": 999, "max_swap_mib": 999999},
            "required_commands": {"definitely-not-pasi-command": {}},
            "required_python_modules": [],
            "required_system_packages": [],
            "runtime_checks": {},
        }
        with mock.patch.object(capabilities.shutil, "which", return_value=None):
            report = capabilities.detect(spec)
        self.assertFalse(report["required_ok"])
        self.assertIn("definitely-not-pasi-command", report["failures"]["commands"])

    def test_minimum_version_is_checked(self) -> None:
        spec = {
            "schema_version": 1,
            "resource_boundary": {"max_memory_mib": 999999, "max_cpu_count": 999, "max_swap_mib": 999999},
            "required_commands": {"python3": {"min_major": 99}},
            "required_python_modules": [],
            "required_system_packages": [],
            "runtime_checks": {},
        }
        with mock.patch.object(capabilities.shutil, "which", return_value="/usr/bin/python3"), \
             mock.patch.object(capabilities.subprocess, "run", return_value=mock.Mock(stdout="Python 3.12.0\n", stderr="", returncode=0)):
            report = capabilities.detect(spec)
        self.assertFalse(report["required_ok"])
        self.assertIn("python3", report["failures"]["commands"])

    def test_report_write_is_atomic(self) -> None:
        payload = {"schema_version": 1, "required_ok": True}
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "capabilities.json"
            capabilities.write_report(path, payload)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), payload)


if __name__ == "__main__":
    unittest.main()


def test_scheduled_health_check_is_detect_only() -> None:
    workflow = Path(".github/workflows/pasi-runner-capabilities.yml").read_text(encoding="utf-8")
    assert "schedule:" in workflow
    assert 'cron: "47 4 * * *"' in workflow
    assert "if: ${{ github.event_name == 'schedule' }}" in workflow
    detect = workflow[workflow.index("  detect-health:"):workflow.index("  reconcile:")]
    assert "Detect runner capabilities" in detect
    assert "--apply" not in detect
    assert "--apply-optional" not in detect


def test_trusted_reconciliation_is_pinned_to_main():
    workflow = Path(".github/workflows/pasi-runner-capabilities.yml").read_text(encoding="utf-8")
    reconcile = workflow[workflow.index("  reconcile:"):]
    assert 'ref: main' in reconcile
    assert "inputs.ref" not in workflow
    assert "Resolve ref" not in reconcile


def test_scheduled_report_verification_reads_runner_temp_environment():
    workflow = Path(".github/workflows/pasi-runner-capabilities.yml").read_text(encoding="utf-8")
    detect = workflow[workflow.index("  detect-health:"):workflow.index("  reconcile:")]
    assert 'REPORT_PATH="$RUNNER_TEMP/pasi-capabilities/capabilities.json" python3' in detect
    assert 'os.environ["REPORT_PATH"]' in detect
