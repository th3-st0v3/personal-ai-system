import unittest


class TestMain(unittest.TestCase):

    def test_main_module_can_be_imported(self):
        import main

        self.assertTrue(callable(main.main))


if __name__ == "__main__":
    unittest.main()
