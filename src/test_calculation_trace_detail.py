import unittest

from calculation_application import CalculationApplication


class TestCalculationTraceDetail(unittest.TestCase):
    def setUp(self):
        self.app = CalculationApplication()

    def test_darcy_trace_contains_intermediate_hydraulic_terms(self):
        trace = self.app.run_trace("darcy_weisbach_pressure_loss", {
            "friction_factor": 0.02,
            "pipe_length": 100,
            "pipe_diameter": 0.1,
            "density": 1000,
            "velocity": 2,
        })
        self.assertGreaterEqual(len(trace.steps), 9)
        self.assertTrue(any("L/D" in step for step in trace.steps))
        self.assertTrue(any("Dynamic-pressure term" in step for step in trace.steps))
        self.assertTrue(any("Pressure loss" in step for step in trace.steps))

    def test_radial_reservoir_trace_contains_resistance_breakdown(self):
        trace = self.app.run_trace("radial_reservoir_flow_rate", {
            "permeability": 1e-13,
            "thickness": 20,
            "pressure_outer": 2e7,
            "pressure_well": 1.5e7,
            "viscosity": 0.001,
            "formation_volume_factor": 1.2,
            "outer_radius": 500,
            "wellbore_radius": 0.1,
            "skin": 2,
        })
        self.assertGreaterEqual(len(trace.steps), 10)
        self.assertTrue(any("Pressure drawdown" in step for step in trace.steps))
        self.assertTrue(any("Radial resistance term" in step for step in trace.steps))
        self.assertTrue(any("Flow denominator" in step for step in trace.steps))
        self.assertGreater(trace.result, 0)


if __name__ == "__main__":
    unittest.main()
