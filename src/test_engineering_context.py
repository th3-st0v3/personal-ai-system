import tempfile
import unittest
from pathlib import Path

from scripts.engineering_context import collect_context


class TestEngineeringContext(unittest.TestCase):
    def test_excludes_runtime_and_secret_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src").mkdir()
            (root / ".runtime").mkdir()
            (root / "src" / "main.py").write_text("print('ok')", encoding="utf-8")
            (root / ".runtime" / "state.json").write_text("{}", encoding="utf-8")
            (root / "secret.key").write_text("private", encoding="utf-8")
            context = collect_context(root)
            self.assertIn("src/main.py", context)
            self.assertNotIn("state.json", context)
            self.assertNotIn("private", context)

    def test_context_is_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "large.md").write_text("x" * 20_000, encoding="utf-8")
            context = collect_context(root, max_chars=2_000, max_file_chars=500)
            self.assertLessEqual(len(context), 2_000)


if __name__ == "__main__":
    unittest.main()
