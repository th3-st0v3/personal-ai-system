from __future__ import annotations

import unittest
from typing import Any, cast

from simulation_library import run_simulation
from simulation_verification import verify_simulation_result


class SimulationVerificationTests(unittest.TestCase):
    def test_valid_result_is_verified(self) -> None:
        result = run_simulation(
            "heat_conduction",
            {
                "conductivity": 2.0,
                "area": 3.0,
                "hot_temperature": 100.0,
                "cold_temperature": 50.0,
                "thickness": 0.5,
            },
        )

        verification = verify_simulation_result(result)

        self.assertEqual(verification.status, "verified")
        self.assertTrue(verification.verified)
        self.assertEqual(verification.failures, ())
        self.assertIn("output fingerprint", verification.checks)
        self.assertIn("provenance fingerprint", verification.checks)

    def test_output_tampering_is_detected(self) -> None:
        result = run_simulation(
            "wellbore_hydraulics",
            {
                "depth": 1000.0,
                "density": 1000.0,
                "diameter": 0.1,
                "velocity": 1.0,
                "viscosity": 0.001,
            },
        )
        tampered = dict(result)
        original_outputs = cast(dict[str, float], result["outputs"])
        tampered_outputs: dict[str, float] = original_outputs.copy()
        tampered_outputs["bottom_pressure"] += 1.0
        tampered["outputs"] = tampered_outputs

        verification = verify_simulation_result(tampered)

        self.assertEqual(verification.status, "failed")
        self.assertFalse(verification.verified)
        self.assertIn(
            "simulation outputs do not match the recorded output fingerprint",
            verification.failures,
        )

    def test_corrupt_provenance_is_detected(self) -> None:
        result = run_simulation(
            "heat_conduction",
            {
                "conductivity": 1.0,
                "area": 1.0,
                "hot_temperature": 90.0,
                "cold_temperature": 20.0,
                "thickness": 1.0,
            },
        )
        tampered = dict(result)
        original_provenance = cast(dict[str, Any], result["provenance"])
        tampered_provenance: dict[str, Any] = original_provenance.copy()
        tampered_provenance["simulation_key"] = "wellbore_hydraulics"
        tampered["provenance"] = tampered_provenance

        verification = verify_simulation_result(tampered)

        self.assertEqual(verification.status, "failed")
        self.assertIn("provenance simulation key does not match result key", verification.failures)

    def test_unknown_schema_is_not_verified(self) -> None:
        result = run_simulation(
            "heat_conduction",
            {
                "conductivity": 1.0,
                "area": 1.0,
                "hot_temperature": 90.0,
                "cold_temperature": 20.0,
                "thickness": 1.0,
            },
        )
        tampered = dict(result)
        tampered["schema_version"] = "999"

        verification = verify_simulation_result(tampered)

        self.assertEqual(verification.status, "failed")
        self.assertIn("schema_version does not match the supported simulation schema", verification.failures)


if __name__ == "__main__":
    unittest.main()
