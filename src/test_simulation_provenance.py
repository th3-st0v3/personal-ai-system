from __future__ import annotations

import unittest
from typing import cast

from simulation_library import SIMULATION_SCHEMA_VERSION, run_simulation


class SimulationValidationAndProvenanceTests(unittest.TestCase):
    def test_wellbore_rejects_non_positive_physical_inputs(self) -> None:
        base = {
            "depth": 1000,
            "density": 1000,
            "diameter": 0.1,
            "velocity": 1,
            "viscosity": 0.001,
        }
        for field in ("depth", "density", "diameter", "velocity", "viscosity"):
            invalid = dict(base)
            invalid[field] = 0
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError, "must be positive"):
                    run_simulation("wellbore_hydraulics", invalid)

    def test_heat_conduction_rejects_non_positive_physical_inputs(self) -> None:
        base = {
            "conductivity": 1,
            "area": 1,
            "hot_temperature": 100,
            "cold_temperature": 50,
            "thickness": 1,
        }
        for field in ("conductivity", "area", "thickness"):
            invalid = dict(base)
            invalid[field] = -1
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError, "must be positive"):
                    run_simulation("heat_conduction", invalid)

    def test_successful_run_has_deterministic_provenance(self) -> None:
        inputs = {
            "depth": 1000,
            "density": 1000,
            "diameter": 0.1,
            "velocity": 1,
            "viscosity": 0.001,
        }
        first = run_simulation("wellbore_hydraulics", inputs)
        second = run_simulation("wellbore_hydraulics", dict(inputs))

        self.assertEqual(first["schema_version"], SIMULATION_SCHEMA_VERSION)
        self.assertEqual(first["provenance"], second["provenance"])
        provenance = cast(dict[str, object], first["provenance"])
        self.assertEqual(provenance["simulation_key"], "wellbore_hydraulics")
        fingerprint = provenance["fingerprint"]
        self.assertIsInstance(fingerprint, str)
        self.assertEqual(len(fingerprint), 64)
        self.assertEqual(first["inputs"], inputs)

    def test_provenance_fingerprint_changes_with_inputs(self) -> None:
        first = run_simulation(
            "heat_conduction",
            {
                "conductivity": 1,
                "area": 1,
                "hot_temperature": 100,
                "cold_temperature": 50,
                "thickness": 1,
            },
        )
        second = run_simulation(
            "heat_conduction",
            {
                "conductivity": 2,
                "area": 1,
                "hot_temperature": 100,
                "cold_temperature": 50,
                "thickness": 1,
            },
        )
        first_provenance = cast(dict[str, object], first["provenance"])
        second_provenance = cast(dict[str, object], second["provenance"])
        self.assertNotEqual(
            first_provenance["fingerprint"],
            second_provenance["fingerprint"],
        )


if __name__ == "__main__":
    unittest.main()
