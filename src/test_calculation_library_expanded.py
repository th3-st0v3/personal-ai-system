import math
import unittest

from calculation_library import CALCULATION_REGISTRY, calculate


class TestExpandedCalculations(unittest.TestCase):
    def test_registry_is_executable_and_traceable(self):
        self.assertGreaterEqual(len(CALCULATION_REGISTRY), 28)
        cases = {
            "ideal_gas_density": {"molar_mass": 0.02897, "pressure": 101325.0, "temperature": 288.15},
            "kinetic_energy": {"mass": 10.0, "velocity": 4.0},
            "gravitational_potential_energy": {"mass": 10.0, "gravity": 9.81, "height": 5.0},
            "spring_force": {"stiffness": 100.0, "displacement": 0.2},
            "spring_potential_energy": {"stiffness": 100.0, "displacement": 0.2},
            "thermal_expansion": {"initial_length": 2.0, "coefficient": 12e-6, "delta_temperature": 50.0},
            "sensible_heat": {"mass": 2.0, "specific_heat": 4186.0, "delta_temperature": 10.0},
            "conduction_heat_rate": {"conductivity": 10.0, "area": 2.0, "delta_temperature": 20.0, "thickness": 0.1},
            "fluid_mass_flow": {"density": 1000.0, "volumetric_flow_rate": 0.002},
            "buoyancy_force": {"fluid_density": 1000.0, "gravity": 9.81, "displaced_volume": 0.01},
            "efficiency": {"useful_output": 80.0, "total_input": 100.0},
            "electrical_resistance_series": {"resistance_1": 10.0, "resistance_2": 20.0},
            "electrical_resistance_parallel": {"resistance_1": 10.0, "resistance_2": 20.0},
            "capacitor_energy": {"capacitance": 0.001, "voltage": 100.0},
            "rc_time_constant": {"resistance": 1000.0, "capacitance": 0.001},
        }
        for key, inputs in cases.items():
            trace = calculate(key, **inputs)
            self.assertEqual(trace.key, key)
            self.assertTrue(trace.equation)
            self.assertTrue(trace.substitutions)
            self.assertEqual(len(trace.steps), 3)
            self.assertTrue(math.isfinite(trace.result))
            self.assertTrue(trace.result_unit)

    def test_known_values(self):
        self.assertAlmostEqual(calculate("kinetic_energy", mass=10.0, velocity=4.0).result, 80.0)
        self.assertAlmostEqual(calculate("gravitational_potential_energy", mass=10.0, gravity=9.81, height=5.0).result, 490.5)
        self.assertAlmostEqual(calculate("spring_force", stiffness=100.0, displacement=-0.2).result, -20.0)
        self.assertAlmostEqual(calculate("spring_potential_energy", stiffness=100.0, displacement=-0.2).result, 2.0)
        self.assertAlmostEqual(calculate("electrical_resistance_series", resistance_1=10.0, resistance_2=20.0).result, 30.0)
        self.assertAlmostEqual(calculate("electrical_resistance_parallel", resistance_1=10.0, resistance_2=20.0).result, 20.0 / 3.0)
        self.assertAlmostEqual(calculate("efficiency", useful_output=80.0, total_input=100.0).result, 0.8)

    def test_invalid_inputs_are_rejected(self):
        invalid = [
            ("ideal_gas_density", {"molar_mass": 0.0, "pressure": 1.0, "temperature": 300.0}),
            ("conduction_heat_rate", {"conductivity": 1.0, "area": 1.0, "delta_temperature": 1.0, "thickness": 0.0}),
            ("efficiency", {"useful_output": 101.0, "total_input": 100.0}),
            ("electrical_resistance_parallel", {"resistance_1": 0.0, "resistance_2": 10.0}),
            ("rc_time_constant", {"resistance": float("nan"), "capacitance": 1.0}),
        ]
        for key, inputs in invalid:
            with self.assertRaises(ValueError):
                calculate(key, **inputs)

    def test_unknown_calculation_is_rejected(self):
        with self.assertRaises(ValueError):
            calculate("does_not_exist", value=1.0)


if __name__ == "__main__":
    unittest.main()
