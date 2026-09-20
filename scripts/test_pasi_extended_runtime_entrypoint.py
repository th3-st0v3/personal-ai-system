from __future__ import annotations

import math
import tempfile
import unittest
from pathlib import Path

from scripts import pasi_extended_runtime_entrypoint as runtime


class ExtendedRuntimeTests(unittest.TestCase):
    def test_weeklong_duration_is_accepted(self) -> None:
        self.assertEqual(runtime.validate_hours(168.0), 168.0)

    def test_longer_duration_is_accepted(self) -> None:
        self.assertEqual(runtime.validate_hours(24.0 * 365.0), 8760.0)

    def test_duration_must_be_finite(self) -> None:
        for value in (math.inf, -math.inf, math.nan):
            with self.assertRaises(ValueError):
                runtime.validate_hours(value)

    def test_duration_must_respect_existing_lower_bound(self) -> None:
        with self.assertRaises(ValueError):
            runtime.validate_hours(runtime.supervisor.MIN_HOURS - 0.01)

    def test_extended_entrypoint_removes_only_the_upper_cap(self) -> None:
        original_supervisor = runtime.supervisor.MAX_HOURS if hasattr(runtime.supervisor, "MAX_HOURS") else None
        try:
            runtime.supervisor.MAX_HOURS = float("inf")
            self.assertTrue(math.isinf(runtime.supervisor.MAX_HOURS))
            self.assertGreater(runtime.validate_hours(168.0), runtime.supervisor.MIN_HOURS)
        finally:
            if original_supervisor is None:
                delattr(runtime.supervisor, "MAX_HOURS")
            else:
                runtime.supervisor.MAX_HOURS = original_supervisor

    def test_task_source_precedence_matches_documented_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            explicit = root / "explicit.md"
            environment = root / "environment.md"
            default = root / "default.md"
            explicit.write_text("explicit task\n", encoding="utf-8")
            environment.write_text("environment-file task\n", encoding="utf-8")
            default.write_text("default-file task\n", encoding="utf-8")

            self.assertEqual(
                runtime.select_task_source(
                    "cli task",
                    explicit,
                    "environment task",
                    environment,
                    default,
                ),
                "cli task",
            )
            self.assertEqual(
                runtime.select_task_source(
                    "",
                    explicit,
                    "environment task",
                    environment,
                    default,
                ),
                "explicit task",
            )
            self.assertEqual(
                runtime.select_task_source(
                    "",
                    None,
                    "environment task",
                    environment,
                    default,
                ),
                "environment task",
            )
            self.assertEqual(
                runtime.select_task_source(
                    "",
                    None,
                    "",
                    environment,
                    default,
                ),
                "environment-file task",
            )
            self.assertEqual(
                runtime.select_task_source(
                    "",
                    None,
                    "",
                    None,
                    default,
                ),
                "default-file task",
            )

    def test_explicit_task_file_is_not_silently_overridden_by_environment_task(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            explicit = Path(directory) / "explicit.md"
            explicit.write_text("the explicit roadmap task\n", encoding="utf-8")
            selected = runtime.select_task_source(
                "",
                explicit,
                "a conflicting environment task",
                None,
                Path(directory) / "missing.md",
            )
            self.assertEqual(selected, "the explicit roadmap task")


if __name__ == "__main__":
    unittest.main()
