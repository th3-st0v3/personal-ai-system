import unittest


class TestMain(unittest.TestCase):

    def test_main_module_can_be_imported(self):
        import main

        self.assertTrue(callable(main.main))


if __name__ == "__main__":
    unittest.main()


class TestCalculationCLI(unittest.TestCase):

    def test_main_module_has_calculation_workflow(self):
        import main

        self.assertTrue(callable(main.run_hydrostatic_calculation))

    def test_hydrostatic_calculation_workflow_uses_user_input(self):
        import main
        from unittest.mock import patch

        with patch(
            "builtins.input",
            side_effect=["1000", "9.81", "10"],
        ), patch("builtins.print") as mock_print:
            record = main.run_hydrostatic_calculation()

        self.assertEqual(record.result, 98100.0)
        mock_print.assert_called_once_with("Pressure: 98100.0 Pa")


if __name__ == "__main__":
    unittest.main()
