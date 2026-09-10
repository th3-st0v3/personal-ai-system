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
    def test_calculation_record_is_immutable(self):
        record = hydrostatic_pressure_record(
            density_kg_m3=1000.0,
            gravity_m_s2=9.81,
            depth_m=10.0,
        )

        with self.assertRaises((AttributeError, TypeError)):
            record.result = 123.0

        with self.assertRaises(TypeError):
            record.inputs["density"] = 500.0

        with self.assertRaises(TypeError):
            record.units["density"] = "g/cm^3"

        self.assertIsInstance(record.assumptions, tuple)
    def test_calculates_darcy_weisbach_pressure_loss(self):
        from calculations import darcy_weisbach_pressure_loss

        pressure_loss = darcy_weisbach_pressure_loss(
            friction_factor=0.02,
            pipe_length_m=100.0,
            pipe_diameter_m=0.1,
            density_kg_m3=1000.0,
            velocity_m_s=2.0,
        )

        self.assertAlmostEqual(pressure_loss, 40000.0)

    def test_rejects_negative_darcy_weisbach_inputs(self):
        from calculations import darcy_weisbach_pressure_loss

        invalid_inputs = [
            (-0.02, 100.0, 0.1, 1000.0, 2.0),
            (0.02, -100.0, 0.1, 1000.0, 2.0),
            (0.02, 100.0, -0.1, 1000.0, 2.0),
            (0.02, 100.0, 0.1, -1000.0, 2.0),
            (0.02, 100.0, 0.1, 1000.0, -2.0),
        ]

        for inputs in invalid_inputs:
            with self.assertRaises(ValueError):
                darcy_weisbach_pressure_loss(*inputs)
    def test_calculates_darcy_weisbach_pressure_loss_record(self):
        from calculations import darcy_weisbach_pressure_loss_record

        record = darcy_weisbach_pressure_loss_record(
            friction_factor=0.02,
            pipe_length_m=100.0,
            pipe_diameter_m=0.1,
            density_kg_m3=1000.0,
            velocity_m_s=2.0,
        )

        self.assertEqual(record.calculation_type, "darcy_weisbach_pressure_loss")
        self.assertEqual(record.inputs["friction_factor"], 0.02)
        self.assertEqual(record.inputs["pipe_length"], 100.0)
        self.assertEqual(record.inputs["pipe_diameter"], 0.1)
        self.assertEqual(record.inputs["density"], 1000.0)
        self.assertEqual(record.inputs["velocity"], 2.0)
        self.assertEqual(record.result, 40000.0)
        self.assertEqual(record.result_unit, "Pa")
        self.assertEqual(
            record.method,
            "ΔP = f * (L / D) * (rho * v^2 / 2)",
        )
if __name__ == "__main__":
    unittest.main()
