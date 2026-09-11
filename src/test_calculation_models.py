import unittest

from calculation_models import CalculationModel, CalculationParameter, MethodVersion


class TestCalculationModels(unittest.TestCase):
    def test_calculation_model_requires_stable_identity(self):
        model = CalculationModel(
            key="hydrostatic_pressure",
            name="Hydrostatic Pressure",
            domain="fluid_pressure",
            description="Pressure from a fluid column.",
            model_type="deterministic_equation",
        )
        self.assertEqual(model.key, "hydrostatic_pressure")

    def test_calculation_model_rejects_empty_key(self):
        with self.assertRaises(ValueError):
            CalculationModel("", "Name", "domain", "description", "type")

    def test_method_version_is_tied_to_model_key(self):
        method = MethodVersion(
            calculation_model_key="hydrostatic_pressure",
            version="1.0",
            equation="P = rho * g * h",
            description="Calculates pressure.",
            applicability="Constant density.",
            assumptions=("constant density",),
            limitations=("No compressibility.",),
        )
        self.assertEqual(method.calculation_model_key, "hydrostatic_pressure")
        self.assertEqual(method.version, "1.0")
        self.assertIsInstance(method.assumptions, tuple)

    def test_parameter_rejects_invalid_range(self):
        with self.assertRaises(ValueError):
            CalculationParameter(
                "hydrostatic_pressure", "depth", "Depth.", "number", True,
                "length", minimum=10.0, maximum=5.0,
            )

    def test_parameter_metadata_is_immutable(self):
        parameter = CalculationParameter(
            "hydrostatic_pressure", "depth", "Depth.", "number", True,
            "length", default_unit="m",
        )
        self.assertEqual(parameter.default_unit, "m")


if __name__ == "__main__":
    unittest.main()
