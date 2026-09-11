import unittest

from calculation_models import (
    CalculationModel,
    CalculationParameter,
    FluidModel,
    MethodVersion,
)


class TestCalculationModelFoundation(unittest.TestCase):
    def test_calculation_model_defines_stable_model_identity(self):
        model = CalculationModel(
            name="Hydrostatic Pressure",
            domain="petroleum",
            description="Pressure from a fluid column.",
            model_type="deterministic",
        )

        self.assertEqual(model.name, "Hydrostatic Pressure")
        self.assertEqual(model.domain, "petroleum")
        self.assertEqual(model.model_type, "deterministic")

    def test_method_version_preserves_versioned_method_metadata(self):
        method = MethodVersion(
            calculation_model_id=1,
            version="1.0",
            equation="P = rho * g * h",
            description="Constant-density hydrostatic pressure.",
            applicability="Single-phase fluid column with constant density.",
            assumptions=("constant density", "constant gravity"),
            limitations=("does not model compressibility",),
            source_id=2,
        )

        self.assertEqual(method.version, "1.0")
        self.assertEqual(method.equation, "P = rho * g * h")
        self.assertEqual(method.assumptions, ("constant density", "constant gravity"))
        self.assertEqual(method.limitations, ("does not model compressibility",))

    def test_method_version_rejects_invalid_model_id(self):
        with self.assertRaises(ValueError):
            MethodVersion(
                calculation_model_id=0,
                version="1.0",
                equation="P = rho * g * h",
                description="test",
                applicability="test",
                assumptions=(),
                limitations=(),
            )

    def test_calculation_parameter_rejects_invalid_range(self):
        with self.assertRaises(ValueError):
            CalculationParameter(
                calculation_model_id=1,
                name="depth",
                description="Measured depth.",
                data_type="number",
                required=True,
                dimension="length",
                minimum=100.0,
                maximum=10.0,
                default_unit="m",
            )

    def test_fluid_model_preserves_property_parameters(self):
        fluid = FluidModel(
            name="Water - Constant Density",
            fluid_type="water",
            model_type="constant_density",
            parameters={"density": 1000.0},
            version="1.0",
            source_id=3,
        )

        self.assertEqual(fluid.parameters["density"], 1000.0)
        with self.assertRaises(TypeError):
            fluid.parameters["density"] = 900.0


if __name__ == "__main__":
    unittest.main()
