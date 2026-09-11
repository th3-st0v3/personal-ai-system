import math
import unittest

from calculation_library import (
    CALCULATION_REGISTRY,
    annular_area,
    annular_velocity,
    equivalent_circulating_density,
    formation_volume_factor,
    hydraulic_power,
    porosity,
    productivity_index,
    radial_reservoir_flow_rate,
    water_saturation,
)


class TestPetroleumCalculations(unittest.TestCase):
    def test_hydraulics_foundations(self):
        self.assertAlmostEqual(annular_area(0.10, 0.05), math.pi * 0.0075 / 4)
        self.assertAlmostEqual(annular_velocity(0.001, 0.10, 0.05), 0.001 / annular_area(0.10, 0.05))
        self.assertEqual(hydraulic_power(100000.0, 0.002), 200.0)
        self.assertAlmostEqual(equivalent_circulating_density(1200.0, 100000.0, 3000.0), 1200.0 + 100000.0 / (9.80665 * 3000.0))

    def test_reservoir_property_and_productivity_calculations(self):
        self.assertEqual(porosity(25.0, 100.0), 0.25)
        self.assertEqual(water_saturation(30.0, 50.0), 0.6)
        self.assertEqual(formation_volume_factor(1.2, 1.0), 1.2)
        self.assertEqual(productivity_index(0.002, 20e6, 18e6), 1e-9)

    def test_radial_reservoir_flow_is_finite_and_positive(self):
        result = radial_reservoir_flow_rate(1e-14, 20.0, 25e6, 20e6, 0.002, 1.2, 500.0, 0.1)
        self.assertTrue(math.isfinite(result))
        self.assertGreater(result, 0.0)

    def test_physical_domain_constraints_are_enforced(self):
        invalid = [
            (annular_area, (0.05, 0.10)),
            (annular_area, (0.10, 0.10)),
            (porosity, (101.0, 100.0)),
            (water_saturation, (51.0, 50.0)),
            (formation_volume_factor, (0.0, 1.0)),
            (productivity_index, (0.002, 18e6, 20e6)),
            (radial_reservoir_flow_rate, (1e-14, 20.0, 25e6, 20e6, 0.002, 1.2, 0.1, 0.1)),
            (equivalent_circulating_density, (1200.0, 100000.0, 0.0)),
        ]
        for function, args in invalid:
            with self.subTest(function=function.__name__):
                with self.assertRaises(ValueError):
                    function(*args)

    def test_petroleum_calculations_are_registered(self):
        expected = {
            "annular_area", "annular_velocity", "hydraulic_power",
            "equivalent_circulating_density", "porosity", "water_saturation",
            "formation_volume_factor", "productivity_index", "radial_reservoir_flow_rate",
        }
        self.assertTrue(expected <= set(CALCULATION_REGISTRY))


if __name__ == "__main__":
    unittest.main()
