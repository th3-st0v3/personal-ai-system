import tempfile
import unittest
from pathlib import Path

from engineering_context import collect_context


class TestEngineeringContext(unittest.TestCase):
    def test_collect_context_bounds_files_and_ignores_sensitive_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src").mkdir()
            (root / "src" / "main.py").write_text("print('ok')", encoding="utf-8")
            (root / ".env").write_text("SECRET=do-not-share", encoding="utf-8")
            (root / "secret.key").write_text("private-key", encoding="utf-8")
            (root / ".runtime").mkdir()
            (root / ".runtime" / "state.json").write_text("private", encoding="utf-8")
            (root / "large.md").write_text("x" * 20_000, encoding="utf-8")
            context = collect_context(root, max_chars=2000, max_file_chars=500)
        self.assertIn("FILE: src/main.py", context)
        self.assertNotIn("SECRET=do-not-share", context)
        self.assertNotIn("private-key", context)
        self.assertNotIn("state.json", context)
        self.assertLessEqual(len(context), 2000)

    def test_collect_context_rejects_missing_root(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                collect_context(Path(directory) / "missing")


if __name__ == "__main__":
    unittest.main()
