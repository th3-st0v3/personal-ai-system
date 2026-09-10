import unittest

from calculations import hydrostatic_pressure


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


if __name__ == "__main__":
    unittest.main()
