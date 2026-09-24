from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.m2_live_acceptance import (
    discover_managed_bridge_pid,
    is_managed_bridge_process,
)


class TestM2LiveAcceptanceContract(unittest.TestCase):
    def test_entrypoint_and_runtime_contracts_are_present(self) -> None:
        entrypoint = Path("scripts/run_m2_live_acceptance.sh").read_text(encoding="utf-8")
        source = Path("scripts/m2_live_acceptance.py").read_text(encoding="utf-8")
        self.assertIn("m2_live_acceptance.py", entrypoint)
        self.assertIn("PASI_RUNTIME_DIR", source)
        self.assertIn("runner.pid", source)
        self.assertIn("bridge.pid", source)
        self.assertIn("start_pasi_168h.sh", source)
        self.assertIn('"--resume"', source)

    def test_m2_does_not_request_a_new_chat(self) -> None:
        source = Path("scripts/run_m2_live_acceptance.sh").read_text(encoding="utf-8")
        self.assertNotIn("new_chat", source)
        self.assertNotIn("new_session", source)

    def test_docs_define_manual_exact_tab_checkpoint(self) -> None:
        source = Path("docs/operations/runtime-acceptance-gates.md").read_text(encoding="utf-8")
        self.assertIn("M2 — kill/restart recovery", source)
        self.assertIn("exact ChatGPT conversation tab", source)
        self.assertIn("same operation ID", source)

    def test_existing_bridge_is_only_accepted_when_pasi_owned(self) -> None:
        repo = str(Path.cwd())
        self.assertTrue(
            is_managed_bridge_process(
                f"{repo}/.venv/bin/python {repo}/scripts/pasi_log_router.py -- -m automation.orchestrator.bridge",
                repo,
            )
        )
        self.assertFalse(
            is_managed_bridge_process(
                "python /tmp/pasi_log_router.py -- -m automation.orchestrator.bridge",
                "/tmp",
            )
        )
        self.assertFalse(
            is_managed_bridge_process(
                f"{repo}/.venv/bin/python -m automation.orchestrator.bridge",
                repo,
            )
        )

    def test_discovery_finds_managed_router_ancestor_of_listener(self) -> None:
        repo = str(Path.cwd())
        commands = {
            4201: f"{repo}/.venv/bin/python -m automation.orchestrator.bridge",
            4100: f"{repo}/.venv/bin/python {repo}/scripts/pasi_log_router.py --log /tmp/bridge.log -- {repo}/.venv/bin/python -m automation.orchestrator.bridge",
        }
        cwd = {4201: repo, 4100: repo}
        parents = {4201: 4100, 4100: 1}
        with (
            patch("scripts.m2_live_acceptance.listening_pids", return_value=[4201]),
            patch("scripts.m2_live_acceptance.process_command", side_effect=commands.__getitem__),
            patch("scripts.m2_live_acceptance.process_cwd", side_effect=cwd.__getitem__),
            patch("scripts.m2_live_acceptance.process_parent", side_effect=parents.__getitem__),
        ):
            found = discover_managed_bridge_pid()
        self.assertIsNotNone(found)
        assert found is not None
        pid, evidence = found
        self.assertEqual(pid, 4100)
        self.assertEqual(evidence["listener_pid"], 4201)
        self.assertEqual(evidence["owner_pid"], 4100)


if __name__ == "__main__":
    unittest.main()
