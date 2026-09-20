from __future__ import annotations

import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from automation.computer_use.obstacles import ObstacleLedger
from scripts import pasi_overnight_engine_v2 as supervisor
from scripts import pasi_overnight_hardening as hardening
from scripts.pasi_overnight_hardening import (
    nonblocking_ensure_services,
    nonblocking_sleep,
    nonblocking_standby,
    resilient_invoke_chat,
    validate_patch_paths,
)


class OvernightHardeningTests(unittest.TestCase):
    def _state(self, root: Path) -> supervisor.OvernightState:
        now = datetime.now(timezone.utc)
        return supervisor.OvernightState(
            schema_version=2,
            run_id="run-1",
            started_at=now.isoformat(),
            deadline_at=(now + timedelta(hours=12)).isoformat(),
            worktree=str(root),
            branch="pasi/test",
            phase="automation",
            current_task="test task",
        )

    def test_backoff_is_deferred_and_recorded_without_sleeping(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = ObstacleLedger(root)
            state = self._state(root)
            started = time.monotonic()
            result = nonblocking_sleep(state, 300.0, ledger=ledger)
            elapsed = time.monotonic() - started
            self.assertTrue(result)
            self.assertLess(elapsed, 1.0)
            self.assertEqual(len(ledger.pending()), 1)
            self.assertEqual(ledger.pending()[0]["kind"], "retry_backoff_deferred")

    def test_stale_browser_uses_fallback_without_entering_standby(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = ObstacleLedger(root)
            state = self._state(root)
            with patch.object(supervisor, "runtime_watchdog_is_live", return_value=False), patch.object(
                hardening, "fallback_providers_available", return_value=["ollama"]
            ), patch.object(supervisor, "time") as time_mock:
                self.assertTrue(nonblocking_standby(state, ledger=ledger))
                time_mock.sleep.assert_not_called()
            self.assertEqual(ledger.pending()[0]["kind"], "runtime_unavailable")

    def test_stale_browser_without_fallback_waits_instead_of_burning_task_attempts(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = ObstacleLedger(root)
            state = self._state(root)
            watchdog = iter([False, False, True])
            with patch.object(supervisor, "runtime_watchdog_is_live", side_effect=lambda: next(watchdog)), patch.object(
                hardening, "fallback_providers_available", return_value=[]
            ), patch.object(supervisor, "ensure_services", return_value=[]), patch.object(
                hardening.time, "sleep"
            ) as sleep_mock:
                self.assertTrue(nonblocking_standby(state, ledger=ledger))
                sleep_mock.assert_called_once()
            self.assertEqual(ledger.pending()[0]["kind"], "runtime_unavailable")

    def test_missing_browser_uses_fallback_route_without_waiting_for_chatgpt(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = ObstacleLedger(root)
            state = self._state(root)
            with patch.object(supervisor, "runtime_watchdog_is_live", return_value=False), patch.object(
                supervisor, "command", return_value=(0, "PASI_RESULT_STATUS: blocked")
            ) as command_mock:
                code, output = resilient_invoke_chat("task", state, "", ledger=ledger)
            self.assertEqual(code, 0)
            self.assertIn("PASI_RESULT_STATUS", output)
            command = command_mock.call_args.args[0]
            self.assertIn("scripts/pasi_provider_router.py", command)
            self.assertNotIn("scripts/pasi_chat_guard.py", command)

    def test_nonblocking_service_recovery_is_native_bridge_only(self) -> None:
        import inspect

        source = inspect.getsource(nonblocking_ensure_services)
        self.assertIn("127.0.0.1:8765/health", source)
        self.assertNotIn("127.0.0.1:8766", source)
        self.assertNotIn("pasi_controller_server.py", source)
        self.assertNotIn("controller_distribution", source)

    def test_patch_guard_rejects_secret_and_symlink_paths(self) -> None:
        with self.assertRaises(ValueError):
            validate_patch_paths(
                "diff --git a/.env b/.env\n--- a/.env\n+++ b/.env\n@@ -1 +1 @@\n-secret\n+secret\n",
                allow_delete=False,
            )
        with self.assertRaises(ValueError):
            validate_patch_paths(
                "diff --git a/link b/link\nnew file mode 120000\n--- /dev/null\n+++ b/link\n@@ -0,0 +1 @@\n+/tmp\n",
                allow_delete=False,
            )


if __name__ == "__main__":
    unittest.main()
