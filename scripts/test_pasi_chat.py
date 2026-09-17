from __future__ import annotations

import unittest

from scripts.pasi_chat import build_prompt


class TestPasiChat(unittest.TestCase):
    def test_build_prompt_contains_task_and_context(self) -> None:
        prompt = build_prompt("inspect the bridge", "Repository remote: example")
        self.assertIn("TASK:\ninspect the bridge", prompt)
        self.assertIn("REPOSITORY / GITHUB CONTEXT:\nRepository remote: example", prompt)
        self.assertIn("does not grant repository write access", prompt)

    def test_build_prompt_does_not_claim_execution(self) -> None:
        prompt = build_prompt("make a change", "clean working tree")
        self.assertIn("Do not claim that files were changed", prompt)


if __name__ == "__main__":
    unittest.main()
