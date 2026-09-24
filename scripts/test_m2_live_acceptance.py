from __future__ import annotations

import unittest
from pathlib import Path


class TestM2LiveAcceptanceContract(unittest.TestCase):
    def test_entrypoint_and_runtime_contracts_are_present(self) -> None:
        source = Path("scripts/run_m2_live_acceptance.sh").read_text(encoding="utf-8")
        self.assertIn("m2_live_acceptance.py", source)
        self.assertIn("PASI_RUNTIME_DIR", source)
        self.assertIn("runner.pid", source)
        self.assertIn("bridge.pid", source)
        self.assertIn("start_pasi_168h.sh --resume", source)

    def test_m2_does_not_request_a_new_chat(self) -> None:
        source = Path("scripts/run_m2_live_acceptance.sh").read_text(encoding="utf-8")
        self.assertNotIn("new_chat", source)
        self.assertNotIn("new_session", source)

    def test_docs_define_manual_exact_tab_checkpoint(self) -> None:
        source = Path("docs/operations/runtime-acceptance-gates.md").read_text(encoding="utf-8")
        self.assertIn("M2 — kill/restart recovery", source)
        self.assertIn("exact ChatGPT conversation tab", source)
        self.assertIn("same operation ID", source)


if __name__ == "__main__":
    unittest.main()
