from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

SUPPORTED_RUNTIME_PATHS = (
    "scripts/pasi_overnight_engine.py",
    "scripts/pasi_overnight_engine_v2.py",
    "scripts/pasi_overnight_hardening.py",
    "scripts/pasi_extended_runtime_entrypoint.py",
    "scripts/start_pasi_overnight.sh",
    "scripts/start_pasi_168h.sh",
    "scripts/stop_pasi_overnight.sh",
    "scripts/status_pasi_overnight.sh",
    "scripts/check_pasi_weekly_run.sh",
)

class TestControllerDistributionRetirement(unittest.TestCase):
    def test_supported_runtime_has_no_legacy_distribution_dependency(self) -> None:
        for relative_path in SUPPORTED_RUNTIME_PATHS:
            source = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertNotIn("127.0.0.1:8766", source, relative_path)
            self.assertNotIn("localhost:8766", source, relative_path)
            self.assertNotIn("pasi_controller_server.py", source, relative_path)
            self.assertNotIn("controller-distribution", source, relative_path)

    def test_browser_catalog_marks_native_controller_canonical(self) -> None:
        catalog = json.loads(
            (ROOT / "config" / "automation" / "setup_catalog.json").read_text(encoding="utf-8")
        )
        downloads = catalog["downloads"]
        native = next(item for item in downloads if item["name"] == "PASI native Chromium extension")
        loader = next(item for item in downloads if item["name"] == "PASI ChatGPT Controller Loader")
        self.assertIs(native["required"], True)
        self.assertNotIn("deprecated", native)
        self.assertIs(loader["required"], False)
        self.assertIs(loader["deprecated"], True)
        self.assertIn("migration-only", loader["reason"])
        self.assertNotIn("8766", json.dumps(loader))

    def test_retired_distribution_files_are_absent(self) -> None:
        self.assertFalse((ROOT / "automation" / "legacy" / "pasi_controller_server.py").exists())
        self.assertFalse((ROOT / "automation" / "legacy" / "test_pasi_controller_server.py").exists())


if __name__ == "__main__":
    unittest.main()
