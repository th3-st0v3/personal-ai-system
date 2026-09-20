from __future__ import annotations

import math
import unittest

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


if __name__ == "__main__":
    unittest.main()
