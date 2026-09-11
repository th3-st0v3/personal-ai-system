import unittest
from unittest.mock import patch

from calculation_application import CalculationApplication
from calculation_definitions import CALCULATION_DEFINITIONS


class TestCalculationApplication(unittest.TestCase):
    def setUp(self):
        self.app = CalculationApplication()

    def test_lists_registered_models_and_metadata(self):
        models = self.app.list_models()
        self.assertEqual(
            [model.key for model in models],
            [model.key for model, _, _ in CALCULATION_DEFINITIONS],
        )
        self.assertEqual(self.app.get_method("hydrostatic_pressure").version, "1.0")
        self.assertEqual(
            [parameter.name for parameter in self.app.get_parameters("darcy_weisbach_pressure_loss")],
            ["friction_factor", "pipe_length", "pipe_diameter", "density", "velocity"],
        )

    def test_runs_hydrostatic_model_through_generic_boundary(self):
        record = self.app.run(
            "hydrostatic_pressure",
            {"density": 1000, "gravity": 9.81, "depth": 10},
        )
        self.assertEqual(record.calculation_type, "hydrostatic_pressure")
        self.assertEqual(record.method_version, "1.0")
        self.assertEqual(record.result, 98100.0)
        self.assertEqual(record.units["depth"], "m")

    def test_runs_darcy_model_through_generic_boundary(self):
        record = self.app.run(
            "darcy_weisbach_pressure_loss",
            {
                "friction_factor": 0.02,
                "pipe_length": 100,
                "pipe_diameter": 0.1,
                "density": 1000,
                "velocity": 2,
            },
        )
        self.assertEqual(record.calculation_type, "darcy_weisbach_pressure_loss")
        self.assertEqual(record.method_version, "1.0")
        self.assertEqual(record.result, 40000.0)
        self.assertEqual(record.result_unit, "Pa")

    def test_runs_expanded_model_through_same_generic_boundary(self):
        record = self.app.run(
            "electrical_power",
            {"voltage": 120, "current": 2},
        )
        self.assertEqual(record.calculation_type, "electrical_power")
        self.assertEqual(record.result, 240.0)
        self.assertEqual(record.result_unit, "W")
        self.assertEqual(record.units["voltage"], "V")

    def test_run_trace_preserves_detailed_solution_for_ui(self):
        trace = self.app.run_trace(
            "hydrostatic_pressure",
            {"density": 1000, "gravity": 9.81, "depth": 10},
        )
        self.assertEqual(trace.result, 98100.0)
        self.assertGreaterEqual(len(trace.steps), 5)
        self.assertEqual(trace.to_dict()["result_unit"], "Pa")

    def test_runs_and_saves_through_application_boundary(self):
        with patch("calculation_application.db.save_calculation_record", return_value=42) as save:
            calculation_id, record = self.app.run_and_save(
                "hydrostatic_pressure",
                {"density": 1000, "gravity": 9.81, "depth": 10},
            )

        self.assertEqual(calculation_id, 42)
        self.assertEqual(record.result, 98100.0)
        save.assert_called_once_with(record)

    def test_rejects_unknown_missing_and_non_numeric_inputs(self):
        with self.assertRaises(ValueError):
            self.app.run("unknown_model", {})
        with self.assertRaises(ValueError):
            self.app.run("hydrostatic_pressure", {"density": 1000, "gravity": 9.81})
        with self.assertRaises(ValueError):
            self.app.run(
                "hydrostatic_pressure",
                {"density": 1000, "gravity": 9.81, "depth": 10, "extra": 1},
            )
        with self.assertRaises(ValueError):
            self.app.run(
                "hydrostatic_pressure",
                {"density": "1000", "gravity": 9.81, "depth": 10},
            )

    def test_rejects_invalid_input_container(self):
        with self.assertRaises(ValueError):
            self.app.run("hydrostatic_pressure", None)

    def test_rejects_non_finite_and_out_of_range_inputs(self):
        with self.assertRaises(ValueError):
            self.app.run(
                "hydrostatic_pressure",
                {"density": float("nan"), "gravity": 9.81, "depth": 10},
            )
        with self.assertRaises(ValueError):
            self.app.run(
                "hydrostatic_pressure",
                {"density": 1000, "gravity": 9.81, "depth": -1},
            )
        with self.assertRaises(ValueError):
            self.app.run(
                "darcy_weisbach_pressure_loss",
                {
                    "friction_factor": 0.02,
                    "pipe_length": 100,
                    "pipe_diameter": 0,
                    "density": 1000,
                    "velocity": 2,
                },
            )


if __name__ == "__main__":
    unittest.main()
