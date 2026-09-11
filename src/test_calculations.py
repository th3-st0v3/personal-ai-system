import os
import tempfile
import unittest

import db
from calculations import (
    darcy_weisbach_pressure_loss,
    darcy_weisbach_pressure_loss_record,
    hydrostatic_pressure,
    hydrostatic_pressure_record,
)


class TestHydrostaticPressure(unittest.TestCase):
    def test_calculates_pressure(self):
        self.assertAlmostEqual(hydrostatic_pressure(1000.0, 9.81, 10.0), 98100.0)

    def test_rejects_negative_inputs(self):
        for inputs in [(-1.0, 9.81, 10.0), (1000.0, -9.81, 10.0), (1000.0, 9.81, -10.0)]:
            with self.assertRaises(ValueError):
                hydrostatic_pressure(*inputs)

    def test_record_uses_definition_metadata(self):
        record = hydrostatic_pressure_record(1000.0, 9.81, 10.0)
        self.assertEqual(record.calculation_type, "hydrostatic_pressure")
        self.assertEqual(record.method_version, "1.0")
        self.assertEqual(record.method, "P = rho * g * h")
        self.assertEqual(record.assumptions, ("constant density", "constant gravitational acceleration"))
        self.assertEqual(dict(record.units), {"density": "kg/m^3", "gravity": "m/s^2", "depth": "m"})
        self.assertEqual(record.result, 98100.0)


class TestDarcyWeisbach(unittest.TestCase):
    def test_calculates_pressure_loss(self):
        self.assertAlmostEqual(darcy_weisbach_pressure_loss(0.02, 100.0, 0.1, 1000.0, 2.0), 40000.0)

    def test_rejects_negative_inputs_and_zero_diameter(self):
        invalid_inputs = [
            (-0.02, 100.0, 0.1, 1000.0, 2.0),
            (0.02, -100.0, 0.1, 1000.0, 2.0),
            (0.02, 100.0, -0.1, 1000.0, 2.0),
            (0.02, 100.0, 0.1, -1000.0, 2.0),
            (0.02, 100.0, 0.1, 1000.0, -2.0),
            (0.02, 100.0, 0.0, 1000.0, 2.0),
        ]
        for inputs in invalid_inputs:
            with self.assertRaises(ValueError):
                darcy_weisbach_pressure_loss(*inputs)

    def test_record_uses_definition_metadata(self):
        record = darcy_weisbach_pressure_loss_record(0.02, 100.0, 0.1, 1000.0, 2.0)
        self.assertEqual(record.calculation_type, "darcy_weisbach_pressure_loss")
        self.assertEqual(record.method_version, "1.0")
        self.assertEqual(record.method, "ΔP = f * (L / D) * (rho * v^2 / 2)")
        self.assertEqual(record.result, 40000.0)


class TestCalculationPersistence(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_path = db.DATABASE_PATH
        db.DATABASE_PATH = os.path.join(self.temp_dir.name, "test.db")

    def tearDown(self):
        db.DATABASE_PATH = self.original_path
        self.temp_dir.cleanup()

    def test_record_persists_model_and_method_version_links(self):
        record = hydrostatic_pressure_record(1000.0, 9.81, 10.0)
        calculation_id = db.save_calculation_record(record)
        retrieved = db.get_calculation_record(calculation_id)
        if retrieved is None:
            self.fail("saved calculation record could not be retrieved")
        self.assertEqual(retrieved.method_version, "1.0")

        connection = db.get_connection()
        links = connection.execute(
            "SELECT calculation_model_id, method_version_id FROM calculation_records WHERE id = ?",
            (calculation_id,),
        ).fetchone()
        connection.close()
        self.assertIsNotNone(links[0])
        self.assertIsNotNone(links[1])


if __name__ == "__main__":
    unittest.main()
