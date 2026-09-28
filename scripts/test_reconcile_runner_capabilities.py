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
