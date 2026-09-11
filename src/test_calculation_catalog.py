import unittest

from calculation_application import CalculationApplication
from calculation_catalog import CATALOG, grouped_categories, list_category, list_categories, search
from calculation_library import CALCULATION_REGISTRY


class TestCalculationCatalog(unittest.TestCase):
    def test_catalog_covers_every_registered_calculation_once(self):
        keys = [entry.key for entry in CATALOG]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(set(keys), set(CALCULATION_REGISTRY))

    def test_shared_calculations_appear_in_multiple_disciplines(self):
        reservoir = set(list_category("Reservoir Engineering"))
        drilling = set(list_category("Drilling Engineering"))
        self.assertIn("hydrostatic_pressure", reservoir)
        self.assertIn("hydrostatic_pressure", drilling)
        self.assertIn("reynolds_number", reservoir)
        self.assertIn("reynolds_number", drilling)
        self.assertTrue(reservoir & drilling)

    def test_search_can_filter_by_category_and_use_case(self):
        self.assertEqual(search("hydrostatic", category="Reservoir Engineering"), ("hydrostatic_pressure",))
        self.assertIn("reynolds_number", search("flow regime", category="Drilling Engineering"))
        electrical = set(search("electrical"))
        self.assertTrue({"ohms_law_voltage", "electrical_power", "electrical_resistance_series", "electrical_resistance_parallel"} <= electrical)

    def test_grouped_categories_are_frontend_ready(self):
        groups = grouped_categories()
        self.assertEqual(tuple(groups), list_categories())
        self.assertIn("Reservoir Engineering", groups)
        self.assertGreater(len(groups["Drilling Engineering"]), 1)

    def test_application_exposes_catalog_without_duplicate_executors(self):
        app = CalculationApplication()
        self.assertEqual(app.list_categories(), list_categories())
        self.assertIn("darcy_weisbach_pressure_loss", app.list_category("Drilling Engineering"))
        self.assertEqual(app.search("Darcy", category="Drilling Engineering"), ("darcy_weisbach_pressure_loss",))
        self.assertIn("Fluid Mechanics", app.get_catalog_entry("reynolds_number").categories)


if __name__ == "__main__":
    unittest.main()
