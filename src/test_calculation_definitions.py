import unittest

from calculation_definitions import CALCULATION_DEFINITIONS, validate_definitions
from calculation_library import CALCULATION_REGISTRY, SPECS


class TestCalculationDefinitions(unittest.TestCase):
    def test_definitions_validate_against_executable_registry(self):
        validate_definitions()
        self.assertEqual(len(CALCULATION_DEFINITIONS), len(SPECS))
        self.assertEqual({model.key for model, _, _ in CALCULATION_DEFINITIONS}, set(CALCULATION_REGISTRY))

    def test_every_parameter_has_a_unit_or_dimension(self):
        for _, _, parameters in CALCULATION_DEFINITIONS:
            for parameter in parameters:
                self.assertTrue(parameter.dimension)
                self.assertTrue(parameter.default_unit)


if __name__ == "__main__":
    unittest.main()
