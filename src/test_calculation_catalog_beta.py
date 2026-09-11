import unittest

from calculation_application import CalculationApplication


class TestCalculationCatalogBeta(unittest.TestCase):
    def setUp(self):
        self.app = CalculationApplication()

    def test_catalog_contains_expanded_engineering_models(self):
        keys = [model.key for model in self.app.list_models()]
        self.assertEqual(len(keys), 9)
        self.assertIn("reynolds_number", keys)
        self.assertIn("hydraulic_power", keys)
        self.assertIn("api_gravity_to_specific_gravity", keys)

    def test_core_flow_models_produce_expected_relationships(self):
        area = self.app.run("pipe_cross_sectional_area", {"pipe_diameter": 0.1})
        flow = self.app.run("volumetric_flow_rate", {"velocity": 2.0, "pipe_diameter": 0.1})
        velocity = self.app.run("fluid_velocity", {"flow_rate": flow.result, "pipe_diameter": 0.1})

        self.assertAlmostEqual(area.result, 3.141592653589793 * 0.1**2 / 4)
        self.assertAlmostEqual(velocity.result, 2.0)
        self.assertAlmostEqual(flow.result, area.result * 2.0)

    def test_reynolds_pressure_gradient_power_and_api_models(self):
        reynolds = self.app.run(
            "reynolds_number",
            {
                "density": 1000,
                "velocity": 2,
                "pipe_diameter": 0.1,
                "dynamic_viscosity": 0.001,
            },
        )
        gradient = self.app.run(
            "hydrostatic_pressure_gradient",
            {"density": 1000, "gravity": 9.81},
        )
        power = self.app.run(
            "hydraulic_power",
            {"pressure_drop": 100000, "flow_rate": 0.02},
        )
        api = self.app.run("api_gravity_to_specific_gravity", {"api_gravity": 35})

        self.assertAlmostEqual(reynolds.result, 200000)
        self.assertAlmostEqual(gradient.result, 9810)
        self.assertAlmostEqual(power.result, 2000)
        self.assertGreater(api.result, 0)
        self.assertLess(api.result, 1)

    def test_explain_returns_equation_steps_and_interpretation(self):
        explanation = self.app.explain(
            "hydrostatic_pressure",
            {"density": 1000, "gravity": 9.81, "depth": 10},
        )

        self.assertEqual(explanation["method"].equation, "P = rho * g * h")
        self.assertGreaterEqual(len(explanation["steps"]), 2)
        self.assertIn("fluid column", explanation["interpretation"])
        self.assertAlmostEqual(explanation["record"].result, 98100)

    def test_expanded_models_keep_validation_strict(self):
        with self.assertRaises(ValueError):
            self.app.run("reynolds_number", {
                "density": 1000,
                "velocity": 2,
                "pipe_diameter": 0.1,
                "dynamic_viscosity": 0,
            })
        with self.assertRaises(ValueError):
            self.app.run("api_gravity_to_specific_gravity", {"api_gravity": -131.5})


if __name__ == "__main__":
    unittest.main()
