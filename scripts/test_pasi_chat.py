from __future__ import annotations

import unittest

from scripts.pasi_chat import build_prompt


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


if __name__ == "__main__":
    unittest.main()
