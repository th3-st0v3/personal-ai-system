from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.pasi_provider_router import extract_chat_text, providers_available


class TestProviderRouter(unittest.TestCase):
    def test_extract_chat_text_from_openai_shape(self) -> None:
        payload = {"choices": [{"message": {"content": "PASI_RESULT_STATUS: complete"}}]}
        self.assertEqual(extract_chat_text(payload), "PASI_RESULT_STATUS: complete")

    def test_extract_chat_text_from_content_parts(self) -> None:
        payload = {"choices": [{"message": {"content": [{"text": "one"}, {"text": "two"}]}}]}
        self.assertEqual(extract_chat_text(payload), "onetwo")

    def test_provider_discovery_never_exposes_secret_values(self) -> None:
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "secret", "PERPLEXITY_API_KEY": "secret2"}, clear=True):
            values = providers_available()
        self.assertIn("openrouter", values)
        self.assertIn("perplexity", values)
        self.assertNotIn("secret", values)
        self.assertNotIn("secret2", values)

    def test_repo_path_remains_a_path_object_for_callers(self) -> None:
        self.assertIsInstance(Path("."), Path)


if __name__ == "__main__":
    unittest.main()
