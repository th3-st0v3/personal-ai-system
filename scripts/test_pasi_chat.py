from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from automation.orchestrator.controller_update import read_last_synced_version, write_sync_state
from scripts.pasi_chat import build_prompt, process_controller_update_signal


class TestPasiChat(unittest.TestCase):
    def test_build_prompt_contains_task_repo_state_and_github_context(self) -> None:
        prompt = build_prompt(
            "inspect the bridge",
            "Repository: https://github.com/example/repo\nWorking tree: clean",
            {},
        )
        self.assertIn("TASK:\ninspect the bridge", prompt)
        self.assertIn("REPOSITORY STATE:\nRepository: https://github.com/example/repo", prompt)
        self.assertIn("GITHUB CONTEXT:", prompt)
        self.assertIn("connected separately through the ChatGPT GitHub app", prompt)
        self.assertIn("does not grant repository write access", prompt)
        self.assertIn("PASI_CONTROLLER_UPDATE: true", prompt)

    def test_build_prompt_includes_bounded_handoff(self) -> None:
        prompt = build_prompt(
            "continue the task",
            "Working tree: clean",
            {
                "chat_url": "https://chatgpt.com/c/example",
                "summary": "Prior verified handoff",
            },
        )
        self.assertIn("Previous PASI ChatGPT session: https://chatgpt.com/c/example", prompt)
        self.assertIn("Previous PASI handoff:\nPrior verified handoff", prompt)

    def test_build_prompt_does_not_claim_execution(self) -> None:
        prompt = build_prompt("make a change", "clean working tree", {})
        self.assertIn("Do not claim that files were changed", prompt)

    def test_normal_response_does_not_stage_controller_update(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controller = root / "automation" / "tampermonkey" / "chatgpt-controller.user.js"
            controller.parent.mkdir(parents=True)
            controller.write_text("// @version      2.4.0\n", encoding="utf-8")
            result = process_controller_update_signal("ordinary answer", root)
            self.assertFalse(result["requested"])
            self.assertFalse((root / ".runtime" / "chatgpt" / "controller-update-request.json").exists())

    def test_explicit_matching_new_version_stages_controller_update(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controller = root / "automation" / "tampermonkey" / "chatgpt-controller.user.js"
            controller.parent.mkdir(parents=True)
            controller.write_text("// @version      2.4.0\n", encoding="utf-8")
            write_sync_state(root / ".runtime" / "chatgpt" / "controller-sync-state.json", version="2.3.0")
            response = (
                "PASI_CONTROLLER_UPDATE: true\n"
                "PASI_CONTROLLER_UPDATE_VERSION: 2.4.0\n"
                "PASI_CONTROLLER_UPDATE_REASON: improve response extraction"
            )
            result = process_controller_update_signal(response, root)
            self.assertTrue(result["eligible"])
            request_path = root / ".runtime" / "chatgpt" / "controller-update-request.json"
            self.assertTrue(request_path.exists())
            self.assertEqual(
                read_last_synced_version(root / ".runtime" / "chatgpt" / "controller-sync-state.json"),
                "2.3.0",
            )


if __name__ == "__main__":
    unittest.main()
