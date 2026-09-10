import unittest

from calculation_records import CalculationRecord


class TestCalculationRecord(unittest.TestCase):

    def test_creates_reproducible_record(self):
        record = CalculationRecord(
            calculation_type="hydrostatic_pressure",
            inputs={
                "density": 1000.0,
                "gravity": 9.81,
                "depth": 10.0,
            },
            units={
                "density": "kg/m^3",
                "gravity": "m/s^2",
                "depth": "m",
            },
            assumptions=[
                "constant density",
                "constant gravitational acceleration",
            ],
            method="P = rho * g * h",
            result=98100.0,
            result_unit="Pa",
            source="user-provided inputs",
        )

        self.assertEqual(
            record.calculation_type,
            "hydrostatic_pressure",
        )
        self.assertEqual(record.inputs["density"], 1000.0)
        self.assertEqual(record.units["depth"], "m")
        self.assertEqual(record.result, 98100.0)
        self.assertEqual(record.result_unit, "Pa")

    def test_record_is_immutable(self):
        record = CalculationRecord(
            calculation_type="hydrostatic_pressure",
            inputs={"density": 1000.0},
            units={"density": "kg/m^3"},
            assumptions=[],
            method="P = rho * g * h",
            result=98100.0,
            result_unit="Pa",
            source="test",
        )

        with self.assertRaises(AttributeError):
            record.result = 123.0

    def test_inputs_are_immutable(self):
        record = CalculationRecord(
            calculation_type="hydrostatic_pressure",
            inputs={"density": 1000.0},
            units={"density": "kg/m^3"},
            assumptions=[],
            method="P = rho * g * h",
            result=98100.0,
            result_unit="Pa",
            source="test",
        )

        with self.assertRaises(TypeError):
            record.inputs["density"] = 999.0

    def test_assumptions_are_immutable(self):
        record = CalculationRecord(
            calculation_type="hydrostatic_pressure",
            inputs={"density": 1000.0},
            units={"density": "kg/m^3"},
            assumptions=["constant density"],
            method="P = rho * g * h",
            result=98100.0,
            result_unit="Pa",
            source="test",
        )

        with self.assertRaises(AttributeError):
            record.assumptions.append("another assumption")


if __name__ == "__main__":
    unittest.main()
