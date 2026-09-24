from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m2_live_acceptance import (
    discover_managed_bridge_pid,
    is_managed_bridge_process,
    queue_operation_ids,
    read_log_since,
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

    def test_marker_operation_ids_are_unique_and_order_preserving(self) -> None:
        with patch(
            "scripts.m2_live_acceptance.queue_items",
            return_value=[
                {"prompt": "M2_ACCEPTANCE_TOKEN", "operation_id": "op-1"},
                {"prompt": "M2_ACCEPTANCE_TOKEN", "operation_id": "op-1"},
                {"prompt": "M2_ACCEPTANCE_TOKEN", "operation_id": "op-2"},
                {"prompt": "other", "operation_id": "op-other"},
            ],
        ):
            self.assertEqual(queue_operation_ids("M2_ACCEPTANCE_TOKEN"), ["op-1", "op-2"])

    def test_resume_acceptance_reads_detached_runner_log(self) -> None:
        source = Path("scripts/m2_live_acceptance.py").read_text(encoding="utf-8")
        self.assertIn('RUNNER_LOG_FILENAME = "runner.log"', source)
        self.assertIn("runner_log_path(runtime_dir)", source)
        self.assertIn("read_log_since(", source)
        self.assertIn("Resuming persisted ChatGPT operation:", source)
        self.assertIn("M2 marker produced duplicate or changed operations after resume", source)

    def test_read_log_since_is_bounded_to_runtime_log_tail(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "runner.log"
            path.write_text("prefix\nResuming persisted ChatGPT operation: op-1\n", encoding="utf-8")
            self.assertIn("Resuming persisted ChatGPT operation: op-1", read_log_since(path, len("prefix\n".encode("utf-8"))))

    def test_runner_kill_requires_zero_restart_budget_evidence(self) -> None:
        source = Path("scripts/m2_live_acceptance.py").read_text(encoding="utf-8")
        self.assertIn("restart budget exhausted after 0 rapid engine exits", source)
        self.assertIn("zero-restart supervisor budget exhaustion evidence", source)
        self.assertIn("PASI_SUPERVISOR_MAX_RESTARTS", source)

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
        self.assertTrue(
            is_managed_bridge_process(
                f"{repo}/.venv/bin/python -m automation.orchestrator.bridge",
                repo,
            )
        )


    def test_managed_bridge_worktree_is_accepted_outside_acceptance_checkout(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tempdir:
            bridge_path = Path(tempdir) / "automation" / "orchestrator"
            bridge_path.mkdir(parents=True)
            (bridge_path / "bridge.py").write_text("# managed bridge\n", encoding="utf-8")
            self.assertTrue(
                is_managed_bridge_process(
                    "/opt/pasi/.venv/bin/python -m automation.orchestrator.bridge",
                    tempdir,
                )
            )

    def test_direct_managed_bridge_is_discovered_from_listener(self) -> None:
        repo = str(Path.cwd())
        commands = {
            4201: f"{repo}/.venv/bin/python -m automation.orchestrator.bridge",
        }
        cwd = {4201: repo}
        parents = {4201: 1}
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
        self.assertEqual(pid, 4201)
        self.assertEqual(evidence["listener_pid"], 4201)

    def test_direct_bridge_kill_identity_accepts_only_pasi_bridge_processes(self) -> None:
        repo = str(Path.cwd())
        self.assertTrue(
            is_managed_bridge_process(
                f"{repo}/.venv/bin/python -m automation.orchestrator.bridge",
                repo,
            )
        )
        self.assertFalse(
            is_managed_bridge_process(
                "/usr/bin/python -m automation.orchestrator.bridge",
                "/tmp",
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
