import unittest

from calculations import hydrostatic_pressure, hydrostatic_pressure_record


class TestHydrostaticPressure(unittest.TestCase):

    def test_calculates_pressure(self):
        pressure = hydrostatic_pressure(
            density_kg_m3=1000.0,
            gravity_m_s2=9.81,
            depth_m=10.0,
        )

        self.assertAlmostEqual(pressure, 98100.0)

    def test_zero_depth_gives_zero_pressure(self):
        pressure = hydrostatic_pressure(
            density_kg_m3=1000.0,
            gravity_m_s2=9.81,
            depth_m=0.0,
        )

        self.assertEqual(pressure, 0.0)

    def test_rejects_negative_density(self):
        with self.assertRaises(ValueError):
            hydrostatic_pressure(-1.0, 9.81, 10.0)

    def test_rejects_negative_gravity(self):
        with self.assertRaises(ValueError):
            hydrostatic_pressure(1000.0, -9.81, 10.0)

    def test_rejects_negative_depth(self):
        with self.assertRaises(ValueError):
            hydrostatic_pressure(1000.0, 9.81, -10.0)

    def test_record_rejects_negative_density(self):
        with self.assertRaises(ValueError):
            hydrostatic_pressure_record(-1.0, 9.81, 10.0)

    def test_record_rejects_negative_gravity(self):
        with self.assertRaises(ValueError):
            hydrostatic_pressure_record(1000.0, -9.81, 10.0)

    def test_record_rejects_negative_depth(self):
        with self.assertRaises(ValueError):
            hydrostatic_pressure_record(1000.0, 9.81, -10.0)

    def test_calculates_pressure_record(self):
        record = hydrostatic_pressure_record(
            density_kg_m3=1000.0,
            gravity_m_s2=9.81,
            depth_m=10.0,
        )

        self.assertEqual(record.calculation_type, "hydrostatic_pressure")
        self.assertEqual(record.inputs["density"], 1000.0)
        self.assertEqual(record.inputs["gravity"], 9.81)
        self.assertEqual(record.inputs["depth"], 10.0)
        self.assertEqual(record.units["density"], "kg/m^3")
        self.assertEqual(record.units["gravity"], "m/s^2")
        self.assertEqual(record.units["depth"], "m")
        self.assertEqual(record.result, 98100.0)
        self.assertEqual(record.result_unit, "Pa")
        self.assertEqual(record.method, "P = rho * g * h")
        self.assertEqual(record.source, "deterministic calculation")

    def test_calculation_record_can_be_persisted(self):
        import db

        record = hydrostatic_pressure_record(
            density_kg_m3=1000.0,
            gravity_m_s2=9.81,
            depth_m=10.0,
        )

        calculation_id = db.save_calculation_record(record)
        retrieved = db.get_calculation_record(calculation_id)

        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.calculation_type, "hydrostatic_pressure")
        self.assertEqual(retrieved.result, 98100.0)
if __name__ == "__main__":
    unittest.main()
