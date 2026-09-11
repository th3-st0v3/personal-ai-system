import unittest

from calculation_library import calculate


class TestCalculationLibrary(unittest.TestCase):
    def test_reynolds_number(self):
        self.assertAlmostEqual(calculate("reynolds_number", density=1000, velocity=2, diameter=0.1, dynamic_viscosity=0.001).result, 200000)

    def test_bernoulli_allows_negative_elevation_datums(self):
        trace = calculate(
            "bernoulli_pressure_downstream",
            pressure_upstream=100000,
            velocity_upstream=2,
            velocity_downstream=3,
            elevation_upstream=-5,
            elevation_downstream=2,
            density=1000,
            gravity=9.81,
            head_loss=1,
        )
        self.assertAlmostEqual(trace.result, 100000 + 1000 * 9.81 * (-5 - 2 - 1) + 0.5 * 1000 * (4 - 9))

    def test_trace_contains_detailed_solution_sections(self):
        trace = calculate("hydrostatic_pressure", density=1000, gravity=9.81, depth=10)
        self.assertEqual(trace.result, 98100)
        self.assertIn("Equation:", trace.steps[0])
        self.assertTrue(any("Substitute values:" in step for step in trace.steps))
        self.assertTrue(any("Report result:" in step and "98100" in step for step in trace.steps))
        self.assertIn("constant density", trace.assumptions)
        self.assertIn("Does not model pressure-dependent density.", trace.limitations)

    def test_trace_serializes_for_ui_and_api(self):
        trace = calculate("electrical_power", voltage=24, current=2)
        payload = trace.to_dict()
        self.assertEqual(payload["key"], "electrical_power")
        self.assertEqual(payload["inputs"], {"voltage": 24, "current": 2})
        self.assertEqual(payload["result"], 48)
        self.assertIsInstance(payload["steps"], list)
        self.assertIsInstance(payload["assumptions"], list)
        self.assertIsInstance(payload["limitations"], list)

    def test_expanded_registry_contains_multiple_domains(self):
        keys = {"hydrostatic_pressure", "darcy_weisbach_pressure_loss", "reynolds_number", "ideal_gas_pressure", "normal_stress", "electrical_power", "mechanical_power"}
        self.assertTrue(keys.issubset(calculate.__globals__["CALCULATION_REGISTRY"]))


if __name__ == "__main__":
    unittest.main()
