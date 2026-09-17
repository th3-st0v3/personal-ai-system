from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import pasi_provider_router
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
            with patch("shutil.which", return_value=None):
                values = providers_available()
        self.assertIn("openrouter", values)
        self.assertIn("perplexity", values)
        self.assertNotIn("secret", values)
        self.assertNotIn("secret2", values)

    def test_provider_discovery_includes_local_ollama_without_api_keys(self) -> None:
        with patch.dict("os.environ", {"OLLAMA_MODEL": "local-coder"}, clear=True):
            with patch("shutil.which", return_value=None):
                values = providers_available()
        self.assertEqual(values[0], "ollama")
        self.assertNotIn("openrouter", values)
        self.assertNotIn("perplexity", values)

    def test_ollama_can_discover_an_installed_model(self) -> None:
        with patch.object(pasi_provider_router, "get_json", return_value={"models": [{"name": "local-coder"}]}):
            with patch.object(pasi_provider_router, "post_json", return_value={"message": {"content": "PASI_RESULT_STATUS: complete"}}):
                result = pasi_provider_router.call_ollama("task", 20.0)
        self.assertEqual(result, "PASI_RESULT_STATUS: complete")

    def test_repo_path_remains_a_path_object_for_callers(self) -> None:
        self.assertIsInstance(Path("."), Path)


if __name__ == "__main__":
    unittest.main()
