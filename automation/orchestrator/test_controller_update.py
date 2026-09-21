from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from .controller_update import (
    evaluate_controller_update,
    parse_controller_update_directive,
    read_controller_version,
    read_last_synced_version,
    write_sync_state,
    write_update_request,
)


class ControllerUpdateProtocolTests(unittest.TestCase):
    def test_default_controller_path_is_isolated_under_legacy_tree(self) -> None:
        from .controller_update import CONTROLLER_PATH

        self.assertEqual(
            CONTROLLER_PATH,
            Path("automation/legacy/tampermonkey/chatgpt-controller.user.js"),
        )

    def test_normal_response_does_not_request_update(self) -> None:
        requested, version, reason = parse_controller_update_directive("The task is complete.")
        self.assertFalse(requested)
        self.assertIsNone(version)
        self.assertEqual(reason, "")

    def test_explicit_directive_requires_version(self) -> None:
        requested, version, reason = parse_controller_update_directive(
            "PASI_CONTROLLER_UPDATE: true\nPASI_CONTROLLER_UPDATE_REASON: Improve response detection"
        )
        self.assertTrue(requested)
        self.assertIsNone(version)
        self.assertIn("Improve response detection", reason)

    def test_false_directive_does_not_trigger(self) -> None:
        requested, version, _ = parse_controller_update_directive(
            "PASI_CONTROLLER_UPDATE: false\nPASI_CONTROLLER_UPDATE_VERSION: 2.4.0"
        )
        self.assertFalse(requested)
        self.assertIsNone(version)

    def test_ready_requires_new_source_version_matching_requested_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "controller.user.js"
            path.write_text("// @version      2.4.0\n", encoding="utf-8")
            decision = evaluate_controller_update(
                "PASI_CONTROLLER_UPDATE: true\nPASI_CONTROLLER_UPDATE_VERSION: 2.4.0\nPASI_CONTROLLER_UPDATE_REASON: test",
                controller_path=path,
                last_synced_version="2.3.0",
            )
            self.assertTrue(decision.eligible)
            self.assertEqual(decision.state, "ready")

    def test_same_synced_version_is_not_reapplied(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "controller.user.js"
            path.write_text("// @version      2.4.0\n", encoding="utf-8")
            decision = evaluate_controller_update(
                "PASI_CONTROLLER_UPDATE: true\nPASI_CONTROLLER_UPDATE_VERSION: 2.4.0",
                controller_path=path,
                last_synced_version="2.4.0",
            )
            self.assertFalse(decision.eligible)
            self.assertEqual(decision.state, "already_synced")

    def test_request_file_and_sync_state_are_bounded_and_parseable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controller = root / "controller.user.js"
            request = root / "request.json"
            state = root / "state.json"
            controller.write_text("// @version      2.4.0\n", encoding="utf-8")
            decision = evaluate_controller_update(
                "PASI_CONTROLLER_UPDATE: true\nPASI_CONTROLLER_UPDATE_VERSION: 2.4.0\nPASI_CONTROLLER_UPDATE_REASON: test",
                controller_path=controller,
                last_synced_version="2.3.0",
            )
            write_update_request(request, decision, source="test")
            self.assertIn('"state": "ready"', request.read_text(encoding="utf-8"))
            write_sync_state(state, version="2.4.0")
            self.assertEqual(read_last_synced_version(state), "2.4.0")
            self.assertEqual(read_controller_version(controller), "2.4.0")


if __name__ == "__main__":
    unittest.main()
