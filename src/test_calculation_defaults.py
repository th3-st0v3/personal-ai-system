import unittest

from calculation_application import CalculationApplication


class TestCalculationDefaults(unittest.TestCase):
    def setUp(self):
        self.app = CalculationApplication()

    def test_default_gravity_is_accepted_when_omitted_and_marked_optional(self):
        trace = self.app.run_trace("pressure_head", {"pressure": 9810, "density": 1000})
        self.assertAlmostEqual(trace.result, 9810 / (1000 * 9.80665), places=12)
        gravity = next(parameter for parameter in self.app.get_parameters("pressure_head") if parameter.name == "gravity")
        self.assertFalse(gravity.required)

    def test_default_gas_constant_is_accepted_when_omitted_and_marked_optional(self):
        trace = self.app.run_trace("ideal_gas_pressure", {"amount": 1, "temperature": 273.15, "volume": 1})
        self.assertAlmostEqual(trace.result, 8.314462618 * 273.15, places=8)
        gas_constant = next(parameter for parameter in self.app.get_parameters("ideal_gas_pressure") if parameter.name == "gas_constant")
        self.assertFalse(gas_constant.required)

    def test_unknown_input_is_still_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unknown inputs"):
            self.app.run_trace("pressure_head", {"pressure": 9810, "density": 1000, "bogus": 1})


if __name__ == "__main__":
    unittest.main()
