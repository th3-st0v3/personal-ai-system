from __future__ import annotations

import unittest

import fuzzing_service
import host_resources


class ExperimentLabTests(unittest.TestCase):
    def test_host_snapshot_has_non_destructive_capabilities(self):
        snapshot = host_resources.host_snapshot()
        self.assertIn("memory", snapshot)
        self.assertIn("swap", snapshot)
        self.assertIn("capabilities", snapshot)
        self.assertTrue(snapshot["capabilities"]["requires_explicit_grant_for_mutation"])

    def test_process_limit_is_bounded(self):
        rows = host_resources.list_processes(limit=9999)
        self.assertLessEqual(len(rows), 250)

    def test_workload_profiles_are_hardware_aware(self):
        profiles = host_resources.workload_profiles()
        self.assertIn(profiles["detected_tier"], profiles["profiles"])
        self.assertLessEqual(
            profiles["profiles"]["Easy"]["fuzz_max_iterations"],
            profiles["profiles"]["Standard"]["fuzz_max_iterations"],
        )
        self.assertLessEqual(
            profiles["profiles"]["Standard"]["fuzz_max_iterations"],
            profiles["profiles"]["Performance"]["fuzz_max_iterations"],
        )

    def test_fuzzer_is_seeded_and_bounded(self):
        first = fuzzing_service.run_fuzz(
            "simulation",
            "heat_conduction",
            {"conductivity": 10, "area": 2, "hot_temperature": 400, "cold_temperature": 300, "thickness": 1},
            iterations=12,
            seed=42,
        )
        second = fuzzing_service.run_fuzz(
            "simulation",
            "heat_conduction",
            {"conductivity": 10, "area": 2, "hot_temperature": 400, "cold_temperature": 300, "thickness": 1},
            iterations=12,
            seed=42,
        )
        self.assertEqual(first["fingerprint"], second["fingerprint"])
        self.assertEqual(first["iterations"], 12)
        self.assertLessEqual(len(first["sample_cases"]), 60)

    def test_fuzzer_rejects_unbounded_request(self):
        with self.assertRaises(ValueError):
            fuzzing_service.run_fuzz("simulation", "heat_conduction", iterations=5001)


if __name__ == "__main__":
    unittest.main()
