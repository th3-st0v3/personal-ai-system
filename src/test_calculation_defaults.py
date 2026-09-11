import unittest

from calculation_application import CalculationApplication


class TestCalculationDefaults(unittest.TestCase):
    def setUp(self):
        self.app = CalculationApplication()

    def test_default_gravity_is_accepted_when_omitted(self):
        trace = self.app.run_trace("pressure_head", {"pressure": 9810, "density": 1000})
        self.assertAlmostEqual(trace.result, 9810 / (1000 * 9.80665), places=12)

    def test_default_gas_constant_is_accepted_when_omitted(self):
        trace = self.app.run_trace("ideal_gas_pressure", {"amount": 1, "temperature": 273.15, "volume": 1})
        self.assertAlmostEqual(trace.result, 8.314462618 * 273.15, places=8)

    def test_unknown_input_is_still_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unknown inputs"):
            self.app.run_trace("pressure_head", {"pressure": 9810, "density": 1000, "bogus": 1})


if __name__ == "__main__":
    unittest.main()
