from __future__ import annotations

import unittest
from pathlib import Path

from scripts.build_chromium_extension import validate_test_bridge_url

ROOT = Path(__file__).resolve().parents[1]


class FreeAcceptanceContractTests(unittest.TestCase):
    def test_free_validation_entrypoint_exists(self) -> None:
        path = ROOT / "scripts" / "run_free_acceptance.py"
        self.assertTrue(path.is_file())
        source = path.read_text(encoding="utf-8")
        self.assertIn('env["PASI_FREE_TEST_MODE"] = "1"', source)
        self.assertIn('"OPENROUTER_API_KEY"', source)

    def test_free_validation_contract_documents_browser_and_interaction_tiers(self) -> None:
        path = ROOT / "docs" / "testing" / "free-validation-contract.md"
        source = path.read_text(encoding="utf-8")
        for marker in (
            "Local interaction validation",
            "Browser fixture acceptance",
            "PASI_FREE_TEST_MODE=1",
            "adapter -> bridge -> browser controller",
        ):
            self.assertIn(marker, source)

    def test_chat_guard_blocks_live_execution_in_free_mode(self) -> None:
        source = (ROOT / "scripts" / "pasi_chat_guard.py").read_text(encoding="utf-8")
        self.assertIn("PASI_FREE_TEST_MODE", source)
        self.assertIn("GUARD_EXIT_FREE_TEST_BLOCKED = 93", source)

    def test_provider_router_exposes_free_mode_network_guard(self) -> None:
        source = (ROOT / "scripts" / "pasi_provider_router.py").read_text(encoding="utf-8")
        self.assertIn("PASI_FREE_TEST_MODE", source)
        self.assertIn("blocks external provider network", source)

    def test_fixture_bridge_urls_are_loopback_only(self) -> None:
        self.assertEqual(validate_test_bridge_url("http://127.0.0.1:43123"), "http://127.0.0.1:43123")
        with self.assertRaises(ValueError):
            validate_test_bridge_url("https://127.0.0.1:43123")
        with self.assertRaises(ValueError):
            validate_test_bridge_url("http://example.com:43123")


if __name__ == "__main__":
    unittest.main()
