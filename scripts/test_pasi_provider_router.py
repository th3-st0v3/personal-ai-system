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

    def test_stalled_ollama_keeps_fallback_time_for_next_provider(self) -> None:
        calls = []

        def fake_ollama(prompt: str, timeout: float) -> str:
            calls.append(("ollama", timeout))
            raise RuntimeError("Ollama timed out")

        def fake_openrouter(prompt: str, timeout: float) -> str:
            calls.append(("openrouter", timeout))
            return "fallback response"

        with patch.object(pasi_provider_router, "providers_available", return_value=["ollama", "openrouter"]):
            with patch.object(pasi_provider_router, "make_prompt", return_value="prompt"):
                with patch.object(pasi_provider_router, "call_ollama", side_effect=fake_ollama):
                    with patch.object(pasi_provider_router, "call_openrouter", side_effect=fake_openrouter):
                        provider, response = pasi_provider_router.route("task", Path("."), 60.0)

        self.assertEqual((provider, response), ("openrouter", "fallback response"))
        self.assertEqual(calls[0][0], "ollama")
        self.assertEqual(calls[0][1], 30.0)
        self.assertEqual(calls[1][0], "openrouter")
        self.assertLess(calls[1][1], 60.0)

    def test_openrouter_429_retry_honors_bounded_retry_after(self) -> None:
        import urllib.error

        calls = []

        def fake_openrouter(prompt: str, timeout: float) -> str:
            calls.append(timeout)
            if len(calls) == 1:
                raise urllib.error.HTTPError(
                    "https://openrouter.ai/api/v1/chat/completions",
                    429,
                    "rate limited",
                    {"Retry-After": "1"},
                    None,
                )
            return "retry response"

        with patch.object(pasi_provider_router, "providers_available", return_value=["openrouter"]):
            with patch.object(pasi_provider_router, "make_prompt", return_value="prompt"):
                with patch.object(pasi_provider_router, "call_openrouter", side_effect=fake_openrouter):
                    with patch.object(pasi_provider_router.time, "sleep") as sleep:
                        provider, response = pasi_provider_router.route("task", Path("."), 30.0)

        self.assertEqual((provider, response), ("openrouter", "retry response"))
        self.assertEqual(len(calls), 2)
        sleep.assert_called_once_with(1.0)

    def test_openrouter_429_zero_retry_after_retries_without_sleep(self) -> None:
        import urllib.error

        calls = []

        def fake_openrouter(prompt: str, timeout: float) -> str:
            calls.append(timeout)
            if len(calls) == 1:
                raise urllib.error.HTTPError(
                    "https://openrouter.ai/api/v1/chat/completions",
                    429,
                    "rate limited",
                    {"Retry-After": "0"},
                    None,
                )
            return "immediate retry response"

        with patch.object(pasi_provider_router, "providers_available", return_value=["openrouter"]):
            with patch.object(pasi_provider_router, "make_prompt", return_value="prompt"):
                with patch.object(pasi_provider_router, "call_openrouter", side_effect=fake_openrouter):
                    with patch.object(pasi_provider_router.time, "sleep") as sleep:
                        provider, response = pasi_provider_router.route("task", Path("."), 30.0)

        self.assertEqual((provider, response), ("openrouter", "immediate retry response"))
        self.assertEqual(len(calls), 2)
        sleep.assert_not_called()

    def test_openrouter_429_does_not_sleep_past_fallback_budget(self) -> None:
        import urllib.error

        error = urllib.error.HTTPError(
            "https://openrouter.ai/api/v1/chat/completions",
            429,
            "rate limited",
            {"Retry-After": "30"},
            None,
        )
        with patch.object(pasi_provider_router, "providers_available", return_value=["openrouter", "ollama"]):
            with patch.object(pasi_provider_router, "make_prompt", return_value="prompt"):
                with patch.object(pasi_provider_router, "call_openrouter", side_effect=error):
                    with patch.object(pasi_provider_router, "call_ollama", return_value="ollama response") as ollama:
                        with patch.object(pasi_provider_router.time, "sleep") as sleep:
                            provider, response = pasi_provider_router.route("task", Path("."), 30.0)

        self.assertEqual((provider, response), ("ollama", "ollama response"))
        sleep.assert_not_called()
        ollama.assert_called_once()


if __name__ == "__main__":
    unittest.main()
