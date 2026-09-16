from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from automation.computer_use.vscode import Diagnostic, VSCodeEvidenceAdapter, VSCodeEvidenceError


class VSCodeEvidenceAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        (self.root / "src").mkdir()
        (self.root / "src" / "app.py").write_text(
            "def calculate(value):\n    return value + 1\n", encoding="utf-8"
        )
        (self.root / "README.md").write_text("calculate the workload\n", encoding="utf-8")
        (self.root / ".venv").mkdir()
        (self.root / ".venv" / "ignored.py").write_text("calculate\n", encoding="utf-8")
        self.adapter = VSCodeEvidenceAdapter(str(self.root), session_id="session-29")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_observe_is_scoped_and_skips_generated_environment_dirs(self) -> None:
        observation = self.adapter.observe()
        self.assertEqual(observation.session_id, "session-29")
        self.assertIn("src/app.py", observation.data["files"])
        self.assertNotIn(".venv/ignored.py", observation.data["files"])
        self.assertEqual(len(observation.data["inventory_fingerprint"]), 64)

    def test_read_file_is_bounded_and_workspace_relative(self) -> None:
        observation = self.adapter.read_file("src/app.py")
        self.assertIn("return value + 1", observation.data["text"])
        with self.assertRaises(VSCodeEvidenceError):
            self.adapter.read_file("../outside.py")
        with self.assertRaises(VSCodeEvidenceError):
            self.adapter.read_file(str(self.root / "src" / "app.py"))

    def test_read_file_rejects_large_content(self) -> None:
        large = self.root / "large.txt"
        large.write_text("x" * 20, encoding="utf-8")
        adapter = VSCodeEvidenceAdapter(str(self.root), session_id="session-29", max_file_bytes=10)
        with self.assertRaises(VSCodeEvidenceError):
            adapter.read_file("large.txt")

    def test_search_is_case_insensitive_deterministic_and_bounded(self) -> None:
        adapter = VSCodeEvidenceAdapter(str(self.root), session_id="session-29", max_search_results=1)
        first = adapter.search("CALCULATE")
        second = adapter.search("CALCULATE")
        self.assertEqual(first.data["matches"], second.data["matches"])
        self.assertEqual(first.data["fingerprint"], second.data["fingerprint"])
        self.assertTrue(first.data["truncated"])
        self.assertEqual(first.data["matches"][0]["path"], "README.md")

    def test_diagnostics_are_normalized_ordered_and_fingerprinted(self) -> None:
        diagnostics_path = self.root / ".pasi-diagnostics.json"
        diagnostics_path.write_text(
            json.dumps(
                {
                    "diagnostics": [
                        {"path": "src/app.py", "line": 4, "column": 1, "severity": "warning", "message": "later"},
                        {"path": "src/app.py", "line": 2, "column": 1, "severity": "error", "message": "first", "source": "Pylance", "code": "reportGeneralTypeIssues"},
                    ]
                }
            ),
            encoding="utf-8",
        )
        adapter = VSCodeEvidenceAdapter(
            str(self.root), session_id="session-29", diagnostics_path=".pasi-diagnostics.json"
        )
        first = adapter.diagnostics()
        second = adapter.diagnostics()
        items = first.data["diagnostics"]
        self.assertEqual(items[0]["line"], 2)
        self.assertEqual(items[0]["source"], "Pylance")
        self.assertEqual(first.data["fingerprint"], second.data["fingerprint"])

    def test_state_snapshot_is_read_only_and_validates_open_files(self) -> None:
        state_path = self.root / ".pasi-state.json"
        state_path.write_text(
            json.dumps(
                {
                    "workspace_name": "personal-ai-system",
                    "active_file": "src/app.py",
                    "open_files": ["README.md", "src/app.py"],
                }
            ),
            encoding="utf-8",
        )
        observation = VSCodeEvidenceAdapter(
            str(self.root), session_id="session-29", state_path=".pasi-state.json"
        ).observe()
        self.assertEqual(observation.data["active_file"], "src/app.py")
        self.assertEqual(observation.data["open_files"], ["README.md", "src/app.py"])

    def test_malformed_diagnostics_and_out_of_root_paths_fail_closed(self) -> None:
        diagnostics_path = self.root / ".pasi-diagnostics.json"
        diagnostics_path.write_text(
            json.dumps(
                {"diagnostics": [{"path": "../secret.py", "line": 1, "column": 1, "severity": "error", "message": "bad"}]}
            ),
            encoding="utf-8",
        )
        adapter = VSCodeEvidenceAdapter(
            str(self.root), session_id="session-29", diagnostics_path=".pasi-diagnostics.json"
        )
        with self.assertRaises(VSCodeEvidenceError):
            adapter.diagnostics()

    def test_diagnostic_fingerprint_is_stable(self) -> None:
        diagnostic = Diagnostic(
            path="src/app.py",
            line=2,
            column=1,
            severity="error",
            message="bad type",
            source="Pylance",
            code="reportGeneralTypeIssues",
        )
        self.assertEqual(diagnostic.fingerprint(), diagnostic.fingerprint())
        self.assertEqual(len(diagnostic.fingerprint()), 64)


if __name__ == "__main__":
    unittest.main()
