from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m2_live_acceptance import (
    BROWSER_MAX_HEARTBEAT_AGE_SECONDS,
    OPERATION_QUEUE_TIMEOUT_SECONDS,
    M2AcceptanceError,
    discover_managed_bridge_pid,
    validate_browser_health,
    is_managed_bridge_process,
    queue_operation_ids,
    read_log_since,
)


class TestM2LiveAcceptanceContract(unittest.TestCase):
    def test_m2_fixture_prompt_does_not_expose_internal_runtime_protocol(self) -> None:
        source = Path("scripts/m2_live_acceptance.py").read_text(encoding="utf-8")
        self.assertIn("isolated live M2 recovery acceptance fixture", source)
        self.assertNotIn("Do not modify tracked files", source)
        self.assertNotIn("LOCAL COMPUTER CAPABILITY PROTOCOL", source)
        self.assertIn("does not require repository implementation changes", source)

    def test_m2_runtime_defaults_to_fresh_isolated_directory(self) -> None:
        source = Path("scripts/m2_live_acceptance.py").read_text(encoding="utf-8")
        self.assertIn('DEFAULT_RUNTIME_BASE_DIR = Path.home() / ".pasi" / "m2-acceptance"', source)
        self.assertIn('runtime_dir_source = "isolated"', source)
        self.assertIn('uuid.uuid4().hex[:8]', source)
        self.assertNotIn('DEFAULT_RUNTIME_DIR = Path.home() / ".pasi" / "overnight"', source)

    def test_m2_queue_wait_allows_detached_runtime_startup_and_captures_diagnostics(self) -> None:
        source = Path("scripts/m2_live_acceptance.py").read_text(encoding="utf-8")
        self.assertGreaterEqual(OPERATION_QUEUE_TIMEOUT_SECONDS, 300.0)
        self.assertIn("runtime_startup_diagnostics(runtime_dir)", source)
        self.assertIn('"operation_start_timeout"', source)

    def test_m2_fast_start_avoids_redundant_launcher_work(self) -> None:
        source = Path("scripts/m2_live_acceptance.py").read_text(encoding="utf-8")
        launcher = Path("scripts/start_pasi_168h.sh").read_text(encoding="utf-8")
        self.assertIn('"PASI_M2_FAST_START": "1"', source)
        self.assertIn('M2_FAST_START="${PASI_M2_FAST_START:-0}"', launcher)
        self.assertIn('skipping redundant setup-check', launcher)
        self.assertIn('browser_deadline=$((SECONDS + 30))', launcher)
        self.assertIn('browser_deadline=$((SECONDS + 5))', launcher)
        self.assertIn('runner_start_deadline=$((SECONDS + 15))', launcher)
        self.assertIn('runner_start_deadline=$((SECONDS + 5))', launcher)

    def test_m2_live_start_records_phase_timings(self) -> None:
        source = Path("scripts/m2_live_acceptance.py").read_text(encoding="utf-8")
        self.assertIn("launcher_start_seconds", source)
        self.assertIn("queue_wait_seconds", source)
        self.assertIn("active_wait_seconds", source)
        self.assertIn("manual_gate_wait_seconds", source)

    def test_m2_operation_poll_is_responsive(self) -> None:
        from scripts.m2_live_acceptance import OPERATION_POLL_SECONDS
        self.assertLessEqual(OPERATION_POLL_SECONDS, 0.25)

    def test_entrypoint_and_runtime_contracts_are_present(self) -> None:
        entrypoint = Path("scripts/run_m2_live_acceptance.sh").read_text(encoding="utf-8")
        source = Path("scripts/m2_live_acceptance.py").read_text(encoding="utf-8")
        self.assertIn("m2_live_acceptance.py", entrypoint)
        self.assertIn('export PYTHONPATH="$REPO_ROOT${PYTHONPATH-}"', entrypoint)
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

    def test_browser_health_preserves_native_v2_envelope_timestamp(self) -> None:
        from unittest.mock import patch
        with patch(
            "scripts.m2_live_acceptance.request_json",
            return_value={
                "observation": {
                    "schema_version": "pasi-native-chromium-v2",
                    "captured_at": "2026-09-24T05:10:05.569Z",
                    "data": {
                        "kind": "chatgpt_health",
                        "native_controller": True,
                    },
                }
            },
        ):
            from scripts.m2_live_acceptance import observation
            value = observation("/browser/health")
        self.assertEqual(value["captured_at"], "2026-09-24T05:10:05.569Z")
        self.assertEqual(value["schema_version"], "pasi-native-chromium-v2")

    def test_browser_health_rejects_missing_extension_version(self) -> None:
        from datetime import datetime, timezone

        captured = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        health = {
            "kind": "chatgpt_health",
            "native_controller": True,
            "manual_reload_gate_supported": True,
            "controller_version": "2.4.11",
            "composer_present": True,
            "conversation_signature": "1:0:fingerprint",
            "chat_url": "https://chatgpt.com/c/example",
            "captured_at": captured,
        }
        with self.assertRaisesRegex(M2AcceptanceError, "stale or unidentified"):
            validate_browser_health(health, "2.4.11", "1.1.3", 30.0)

    def test_browser_health_requires_fresh_timestamp_and_same_conversation(self) -> None:
        from datetime import datetime, timedelta, timezone

        stale = (datetime.now(timezone.utc) - timedelta(seconds=31)).isoformat().replace("+00:00", "Z")
        health = {
            "kind": "chatgpt_health",
            "native_controller": True,
            "controller_version": "2.4.11",
            "extension_manifest_version": "1.1.3",
            "composer_present": True,
            "conversation_signature": "1:0:fingerprint",
            "chat_url": "https://chatgpt.com/c/example",
            "captured_at": stale,
        }
        with self.assertRaisesRegex(M2AcceptanceError, "heartbeat is stale"):
            validate_browser_health(health, "2.4.11", "1.1.3", 30.0)

        fresh = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        health["captured_at"] = fresh
        with self.assertRaisesRegex(M2AcceptanceError, "conversation URL changed"):
            validate_browser_health(
                health,
                "2.4.11",
                "1.1.3",
                30.0,
                expected_chat_url="https://chatgpt.com/c/other",
            )

    def test_manual_checkpoint_prints_exact_tab_reopen_fallback_commands(self) -> None:
        source = Path("scripts/m2_live_acceptance.py").read_text(encoding="utf-8")
        self.assertIn("PASI will attempt to reopen the same conversation automatically", source)
        self.assertIn("powershell.exe -NoProfile -Command", source)
        self.assertIn("cmd.exe /c start", source)

    def test_manual_reload_gate_requires_fresh_same_conversation_health(self) -> None:
        source = Path("scripts/m2_live_acceptance.py").read_text(encoding="utf-8")
        self.assertIn("def fresh_reload_health()", source)
        self.assertIn("expected_chat_url=chat_url", source)
        self.assertIn("fresh native browser health after the manual exact-tab reload", source)
        self.assertIn("wait_for(", source)

    def test_m2_requires_controller_manual_reload_gate_capability(self) -> None:
        from datetime import datetime, timezone

        health = {
            "kind": "chatgpt_health",
            "native_controller": True,
            "controller_version": "2.4.11",
            "extension_manifest_version": "1.1.3",
            "composer_present": True,
            "conversation_signature": "1:0:fingerprint",
            "chat_url": "https://chatgpt.com/c/example",
            "captured_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        with self.assertRaisesRegex(M2AcceptanceError, "manual reload gate capability"):
            validate_browser_health(
                health,
                "2.4.11",
                "1.1.3",
                30.0,
                require_manual_reload_gate_capability=True,
            )
        health["manual_reload_gate_supported"] = True
        validate_browser_health(
            health,
            "2.4.11",
            "1.1.3",
            30.0,
            require_manual_reload_gate_capability=True,
        )

    def test_browser_health_accepts_fresh_same_conversation(self) -> None:
        from datetime import datetime, timezone

        health = {
            "kind": "chatgpt_health",
            "native_controller": True,
            "controller_version": "2.4.11",
            "extension_manifest_version": "1.1.3",
            "composer_present": True,
            "conversation_signature": "1:0:fingerprint",
            "chat_url": "https://chatgpt.com/c/example",
            "captured_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        age = validate_browser_health(health, "2.4.11", "1.1.3", 30.0, "https://chatgpt.com/c/example")
        self.assertGreaterEqual(age, -5.0)
        self.assertLessEqual(age, 30.0)
    def test_manual_reload_gate_requires_armed_nonterminal_operation_and_release(self) -> None:
        source = Path("scripts/m2_live_acceptance.py").read_text(encoding="utf-8")
        self.assertIn("PASI_M2_MANUAL_RELOAD_GATE: true", source)
        self.assertIn("manual_reload_gate_armed", source)
        self.assertIn('"/chat/manual-reload-gate/release"', source)
        self.assertIn("PASI_M2_MANUAL_RELOAD_GATE_RELEASE", source)

    def test_m2_preflight_rejects_stale_browser_health(self) -> None:
        source = Path("scripts/m2_live_acceptance.py").read_text(encoding="utf-8")
        self.assertIn("BROWSER_MAX_HEARTBEAT_AGE_SECONDS", source)
        self.assertIn("browser heartbeat is stale", source)
        self.assertIn("expected_controller_version(REPO_ROOT)", source)
        self.assertIn("expected_extension_manifest_version(REPO_ROOT)", source)
        self.assertEqual(BROWSER_MAX_HEARTBEAT_AGE_SECONDS, 30.0)

    def test_failure_path_cleans_up_managed_runtime(self) -> None:
        source = Path("scripts/m2_live_acceptance.py").read_text(encoding="utf-8")
        self.assertIn("runner_started = False", source)
        self.assertIn("bridge_was_stopped = False", source)
        self.assertIn("try_kill_managed_tree(", source)
        self.assertIn('"supervisor.pid"', source)
        self.assertIn('"runner.pid"', source)
        self.assertIn('"bridge_restore"', source)

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
