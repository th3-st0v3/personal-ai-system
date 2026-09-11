import unittest
from unittest.mock import patch

class TestMain(unittest.TestCase):

    def test_main_module_can_be_imported(self):
        import main

        self.assertTrue(callable(main.main))


    def test_projects_menu_creates_project(self):
        import main

        with patch(
            "builtins.input",
            side_effect=["1", "Test Project", "Test description", "3"],
        ), patch(
            "main.create_project",
            return_value=42,
        ) as mock_create, patch(
            "builtins.print"
        ) as mock_print:
            main.projects_menu()

        mock_create.assert_called_once_with(
            "Test Project",
            "Test description",
        )
        mock_print.assert_any_call(
            "Project created with id 42."
        )


    def test_projects_menu_lists_projects(self):
        import main

        projects = [
            (1, "Project Alpha", "First project"),
            (2, "Project Beta", None),
        ]

        with patch(
            "builtins.input",
            side_effect=["2", "3"],
        ), patch(
            "main.get_projects",
            return_value=projects,
        ), patch("builtins.print") as mock_print:
            main.projects_menu()

        mock_print.assert_any_call(
            "1. Project Alpha - First project"
        )
        mock_print.assert_any_call(
            "2. Project Beta - "
        )


    def test_requirements_menu_creates_requirement(self):
        import main

        with patch(
            "builtins.input",
            side_effect=["1", "42", "System must calculate pressure", "6"],
        ), patch(
            "main.create_requirement",
            return_value=7,
        ) as mock_create, patch(
            "builtins.print"
        ) as mock_print:
            main.requirements_menu()

        mock_create.assert_called_once_with(
            42,
            "System must calculate pressure",
        )
        mock_print.assert_any_call(
            "Requirement created with id 7."
        )


    def test_requirements_menu_views_requirement(self):
        import main

        requirement = (
            1,
            1,
            "Project Alpha",
            "Verify pressure system",
            "unverified",
        )

        evidence = [
            (
                1,
                1,
                "pressure test report",
                "report.pdf",
                "Pressure test passed",
                "verified",
            )
        ]

        with patch(
            "builtins.input",
            side_effect=["2", "1", "6"],
        ), patch(
            "main.get_requirement",
            return_value=requirement,
        ), patch(
            "main.get_evidence_for_requirement",
            return_value=evidence,
        ), patch("builtins.print") as mock_print:
            main.requirements_menu()

        mock_print.assert_any_call(
            "\nRequirement 1: Verify pressure system"
        )
        mock_print.assert_any_call(
            "Project: Project Alpha"
        )
        mock_print.assert_any_call(
            "Status: unverified"
        )
        mock_print.assert_any_call(
            "  - [verified] pressure test report "
            "(report.pdf): Pressure test passed"
        )


    def test_requirements_menu_updates_requirement_status(self):
        import main

        requirement = (
            42,
            1,
            "Project Alpha",
            "Verify pressure system",
            "unverified",
        )

        with patch(
            "builtins.input",
            side_effect=["3", "42", "1", "6"],
        ), patch(
            "main.get_requirement",
            return_value=requirement,
        ), patch(
            "main.update_requirement_status"
        ) as mock_update, patch("builtins.print"):
            main.requirements_menu()

        mock_update.assert_called_once_with(
            42,
            "Verified",
        )


    def test_requirements_menu_evaluates_requirement_evidence(self):
        import main

        requirement = (
            42,
            1,
            "Project Alpha",
            "Verify pressure system",
            "unverified",
        )

        evaluation = {
            "recommendation": "verified",
            "signals": ["verified"],
            "conflict": False,
        }

        with patch(
            "builtins.input",
            side_effect=["4", "42", "6"],
        ), patch(
            "main.get_requirement",
            return_value=requirement,
        ), patch(
            "main.evaluate_requirement_evidence",
            return_value=evaluation,
        ) as mock_evaluate, patch(
            "builtins.print"
        ) as mock_print:
            main.requirements_menu()

        mock_evaluate.assert_called_once_with(42)

        mock_print.assert_any_call(
            "\nRequirement 42: Verify pressure system"
        )
        mock_print.assert_any_call(
            "Current status: unverified"
        )
        mock_print.assert_any_call(
            "Evidence assessment: verified"
        )
        mock_print.assert_any_call(
            "Evidence signals: verified"
        )
        mock_print.assert_any_call(
            "Conflict: No"
        )


    def test_requirements_menu_views_evidence_history(self):
        import main

        requirement = (
            42,
            1,
            "Project Alpha",
            "Verify pressure system",
            "unverified",
        )

        history = [
            (
                7,
                42,
                "Pressure test",
                "test_report.pdf",
                "Pressure held at 100 psi",
                "Verified",
                0,
                "2026-09-10T12:00:00",
            )
        ]

        with patch(
            "builtins.input",
            side_effect=["5", "42", "6"],
        ), patch(
            "main.get_requirement",
            return_value=requirement,
        ), patch(
            "main.get_evidence_history_for_requirement",
            return_value=history,
        ) as mock_history, patch(
            "builtins.print"
        ) as mock_print:
            main.requirements_menu()

        mock_history.assert_called_once_with(42)

        mock_print.assert_any_call(
            "\nEvidence history for requirement 42: "
            "Verify pressure system"
        )
        mock_print.assert_any_call(
            "  - [Verified] Pressure test "
            "(test_report.pdf): Pressure held at 100 psi "
            "[0] at 2026-09-10T12:00:00"
        )


    def test_requirements_menu_handles_non_numeric_requirement_id(self):
        import main

        with patch(
            "builtins.input",
            side_effect=["2", "not-a-number", "6"],
        ), patch(
            "builtins.print"
        ) as mock_print:
            main.requirements_menu()

        mock_print.assert_any_call(
            "Requirement id must be a number."
        )


    def test_requirements_menu_handles_missing_requirement(self):
        import main

        with patch(
            "builtins.input",
            side_effect=["2", "42", "6"],
        ), patch(
            "main.get_requirement",
            return_value=None,
        ), patch(
            "builtins.print"
        ) as mock_print:
            main.requirements_menu()

        mock_print.assert_any_call(
            "No requirement with that id."
        )


    def test_requirements_menu_status_handles_missing_requirement(self):
        import main

        with patch(
            "builtins.input",
            side_effect=["3", "42", "6"],
        ), patch(
            "main.get_requirement",
            return_value=None,
        ), patch(
            "main.update_requirement_status"
        ) as mock_update, patch(
            "builtins.print"
        ) as mock_print:
            main.requirements_menu()

        mock_update.assert_not_called()
        mock_print.assert_any_call(
            "No requirement with that id."
        )

    def test_requirements_menu_status_handles_invalid_status_choice(self):
        import main

        requirement = (
            42,
            1,
            "Project Alpha",
            "Verify pressure system",
            "unverified",
        )

        with patch(
            "builtins.input",
            side_effect=["3", "42", "9", "6"],
        ), patch(
            "main.get_requirement",
            return_value=requirement,
        ), patch(
            "main.update_requirement_status"
        ) as mock_update, patch(
            "builtins.print"
        ) as mock_print:
            main.requirements_menu()

        mock_update.assert_not_called()
        mock_print.assert_any_call(
            "Invalid choice, status not changed."
        )


    def test_requirements_menu_evaluation_handles_non_numeric_requirement_id(self):
        import main

        with patch(
            "builtins.input",
            side_effect=["4", "not-a-number", "6"],
        ), patch(
            "main.evaluate_requirement_evidence"
        ) as mock_evaluate, patch(
            "builtins.print"
        ) as mock_print:
            main.requirements_menu()

        mock_evaluate.assert_not_called()
        mock_print.assert_any_call(
            "Requirement id must be a number."
        )


    def test_requirements_menu_history_handles_non_numeric_requirement_id(self):
        import main

        with patch(
            "builtins.input",
            side_effect=["5", "not-a-number", "6"],
        ), patch(
            "main.get_requirement"
        ) as mock_get, patch(
            "main.get_evidence_history_for_requirement"
        ) as mock_history, patch(
            "builtins.print"
        ) as mock_print:
            main.requirements_menu()

        mock_get.assert_not_called()
        mock_history.assert_not_called()
        mock_print.assert_any_call(
            "Requirement id must be a number."
        )


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


    def test_recent_calculations_workflow_displays_multiple_records(self):
        import main
        from calculation_records import CalculationRecord

        records = [
            CalculationRecord(
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
            ),
            CalculationRecord(
                calculation_type="darcy_weisbach_pressure_loss",
                inputs={
                    "friction_factor": 0.02,
                    "pipe_length": 100,
                    "pipe_diameter": 0.1,
                    "density": 1000,
                    "velocity": 2,
                },
                units={
                    "friction_factor": "dimensionless",
                    "pipe_length": "m",
                    "pipe_diameter": "m",
                    "density": "kg/m^3",
                    "velocity": "m/s",
                },
                assumptions=(
                    "constant density",
                    "steady flow",
                ),
                method="ΔP = f * (L / D) * (rho * v^2 / 2)",
                result=40000.0,
                result_unit="Pa",
                source="deterministic calculation",
            ),
        ]

        with patch(
            "main.get_recent_calculation_records",
            return_value=records,
        ), patch("builtins.print") as mock_print:
            main.run_recent_calculations()

        mock_print.assert_any_call(
            "1. hydrostatic_pressure: 98100.0 Pa"
        )
        mock_print.assert_any_call(
            "2. darcy_weisbach_pressure_loss: 40000.0 Pa"
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


    def test_calculations_menu_handles_invalid_option(self):
        import main

        with patch(
            "builtins.input",
            side_effect=["9", "4"],
        ), patch("builtins.print") as mock_print:
            main.calculations_menu()

        mock_print.assert_any_call(
            "Invalid option. Please choose 1-4."
        )


if __name__ == "__main__":
    unittest.main()
