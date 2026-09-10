import unittest
from unittest.mock import patch

class TestMain(unittest.TestCase):

    def test_main_module_can_be_imported(self):
        import main

        self.assertTrue(callable(main.main))


class TestCalculationCLI(unittest.TestCase):

    def test_main_module_has_calculation_workflow(self):
        import main

        self.assertTrue(callable(main.run_hydrostatic_calculation))

    def test_hydrostatic_calculation_workflow_uses_user_input(self):
        import main

        with patch(
            "builtins.input",
            side_effect=["1000", "9.81", "10"],
        ), patch("builtins.print") as mock_print:
            record = main.run_hydrostatic_calculation()

        self.assertEqual(record.result, 98100.0)
        mock_print.assert_called_once_with("Pressure: 98100.0 Pa")

    def test_hydrostatic_calculation_workflow_saves_record(self):
        import main

        with patch(
            "builtins.input",
            side_effect=["1000", "9.81", "10"],
        ), patch("builtins.print"), patch(
            "main.save_calculation_record"
        ) as mock_save:
            record = main.run_hydrostatic_calculation()

        mock_save.assert_called_once_with(record)

    def test_recent_calculations_workflow_displays_saved_records(self):
        import main
        from calculation_records import CalculationRecord

        record = CalculationRecord(
            calculation_type="hydrostatic_pressure",
            inputs={
                "density": 1000,
                "gravity": 9.81,
                "depth": 10,
            },
            units={
                "density": "kg/m^3",
                "gravity": "m/s^2",
                "depth": "m",
            },
            assumptions=(
                "constant density",
                "constant gravitational acceleration",
            ),
            method="P = rho * g * h",
            result=98100.0,
            result_unit="Pa",
            source="deterministic calculation",
        )

        with patch(
            "main.get_recent_calculation_records",
            return_value=[record],
        ), patch("builtins.print") as mock_print:
            main.run_recent_calculations()

        mock_print.assert_any_call(
            "1. hydrostatic_pressure: 98100.0 Pa"
        )

    def test_recent_calculations_workflow_handles_no_records(self):
        import main

        with patch(
            "main.get_recent_calculation_records",
            return_value=[],
        ), patch("builtins.print") as mock_print:
            main.run_recent_calculations()

        mock_print.assert_called_once_with(
            "No calculations saved."
        )


    def test_darcy_weisbach_calculation_workflow_saves_record(self):
        from main import run_darcy_weisbach_calculation

        with patch("builtins.input", side_effect=[
            "0.02",
            "100",
            "0.1",
            "1000",
            "2",
        ]):
            with patch("main.save_calculation_record") as save_record:
                record = run_darcy_weisbach_calculation()

        self.assertEqual(
            record.calculation_type,
            "darcy_weisbach_pressure_loss",
        )
        self.assertEqual(record.result, 40000.0)
        save_record.assert_called_once_with(record)


class TestMainMenu(unittest.TestCase):

    def test_main_menu_has_organized_top_level_options(self):
        import main

        with patch(
            "builtins.input",
            side_effect=["7"],
        ), patch("builtins.print") as mock_print:
            main.main()

        printed = [
            call.args[0]
            for call in mock_print.call_args_list
            if call.args
        ]

        self.assertIn("1. Notes", printed)
        self.assertIn("2. Projects", printed)
        self.assertIn("3. Requirements", printed)
        self.assertIn("4. Evidence", printed)
        self.assertIn("5. Calculations", printed)
        self.assertIn("6. Ask AI", printed)
        self.assertIn("7. Quit", printed)

    def test_notes_menu_has_back_option(self):
        import main

        with patch(
            "builtins.input",
            side_effect=["1", "4", "7"],
        ), patch("builtins.print") as mock_print:
            main.main()

        printed = [
            call.args[0]
            for call in mock_print.call_args_list
            if call.args
        ]

        self.assertIn("1. Add a note", printed)
        self.assertIn("2. View notes", printed)
        self.assertIn("3. Search notes", printed)
        self.assertIn("4. Back", printed)


class TestCalculationsMenu(unittest.TestCase):

    def test_calculations_menu_runs_darcy_weisbach(self):
        import main

        with patch(
            "builtins.input",
            side_effect=["2", "4"],
        ), patch(
            "main.run_darcy_weisbach_calculation"
        ) as mock_run:
            main.calculations_menu()

        mock_run.assert_called_once_with()


    def test_darcy_weisbach_calculation_workflow_uses_user_input(self):
        import main

        with patch(
            "builtins.input",
            side_effect=[
                "0.02",
                "100",
                "0.1",
                "1000",
                "2",
            ],
        ), patch("builtins.print") as mock_print:
            record = main.run_darcy_weisbach_calculation()

        self.assertEqual(record.result, 40000.0)
        mock_print.assert_called_once_with(
            "Pressure loss: 40000.0 Pa"
        )


    def test_calculations_menu_runs_recent_calculations(self):
        import main

        with patch(
            "builtins.input",
            side_effect=["3", "4"],
        ), patch(
            "main.run_recent_calculations"
        ) as mock_run:
            main.calculations_menu()

        mock_run.assert_called_once_with()


    def test_calculations_menu_runs_hydrostatic(self):
        import main

        with patch(
            "builtins.input",
            side_effect=["1", "4"],
        ), patch(
            "main.run_hydrostatic_calculation"
        ) as mock_run:
            main.calculations_menu()

        mock_run.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
