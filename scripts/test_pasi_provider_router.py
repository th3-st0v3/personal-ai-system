from __future__ import annotations

from email.message import Message
import unittest
from pathlib import Path
import tempfile
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

    def test_remote_provider_discovery_requires_explicit_opt_in(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "OPENROUTER_API_KEY": "secret",
                "PERPLEXITY_API_KEY": "secret2",
                "PASI_ALLOW_REMOTE_CODE": "",
            },
            clear=True,
        ):
            with patch("shutil.which", return_value=None):
                values = providers_available()
        self.assertNotIn("openrouter", values)
        self.assertNotIn("perplexity", values)
        self.assertNotIn("secret", values)
        self.assertNotIn("secret2", values)

        with patch.dict(
            "os.environ",
            {
                "OPENROUTER_API_KEY": "secret",
                "PERPLEXITY_API_KEY": "secret2",
                "PASI_ALLOW_REMOTE_CODE": "1",
            },
            clear=True,
        ):
            with patch("shutil.which", return_value=None):
                values = providers_available()
        self.assertIn("openrouter", values)
        self.assertIn("perplexity", values)

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
                headers = Message()
                headers["Retry-After"] = "1"
                raise urllib.error.HTTPError(
                    "https://openrouter.ai/api/v1/chat/completions",
                    429,
                    "rate limited",
                    headers,
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

    def test_openrouter_429_missing_retry_after_uses_short_bounded_retry(self) -> None:
        import urllib.error

        calls = []

        def fake_openrouter(prompt: str, timeout: float) -> str:
            calls.append(timeout)
            if len(calls) == 1:
                raise urllib.error.HTTPError(
                    "https://openrouter.ai/api/v1/chat/completions",
                    429,
                    "rate limited",
                    Message(),
                    None,
                )
            return "headerless retry response"

        with patch.object(pasi_provider_router, "providers_available", return_value=["openrouter"]):
            with patch.object(pasi_provider_router, "make_prompt", return_value="prompt"):
                with patch.object(pasi_provider_router, "call_openrouter", side_effect=fake_openrouter):
                    with patch.object(pasi_provider_router.time, "sleep") as sleep:
                        provider, response = pasi_provider_router.route("task", Path("."), 30.0)

        self.assertEqual((provider, response), ("openrouter", "headerless retry response"))
        self.assertEqual(len(calls), 2)
        sleep.assert_called_once_with(1.0)

    def test_openrouter_429_zero_retry_after_retries_without_sleep(self) -> None:
        import urllib.error

        calls = []

        def fake_openrouter(prompt: str, timeout: float) -> str:
            calls.append(timeout)
            if len(calls) == 1:
                headers = Message()
                headers["Retry-After"] = "0"
                raise urllib.error.HTTPError(
                    "https://openrouter.ai/api/v1/chat/completions",
                    429,
                    "rate limited",
                    headers,
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

        headers = Message()
        headers["Retry-After"] = "30"
        error = urllib.error.HTTPError(
            "https://openrouter.ai/api/v1/chat/completions",
            429,
            "rate limited",
            headers,
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

    def test_provider_order_is_local_before_opted_in_remote(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "OLLAMA_MODEL": "local-coder",
                "PASI_ALLOW_REMOTE_CODE": "1",
                "OPENROUTER_API_KEY": "remote",
                "PERPLEXITY_API_KEY": "remote2",
            },
            clear=True,
        ):
            with patch("shutil.which", side_effect=lambda name: "/usr/bin/opencode" if name == "opencode" else None):
                self.assertEqual(
                    providers_available(),
                    ["ollama", "opencode", "openrouter", "perplexity"],
                )


    def test_openrouter_uses_task_only_prompt_on_free_tier(self) -> None:
        captured: list[str] = []

        def fake_openrouter(prompt: str, timeout: float) -> str:
            captured.append(prompt)
            return "safe response"

        with patch.dict(
            "os.environ",
            {
                "OPENROUTER_API_KEY": "remote",
                "PASI_ALLOW_REMOTE_CODE": "1",
            },
            clear=True,
        ):
            with patch.object(pasi_provider_router, "collect_context", return_value="PRIVATE-SENTINEL"):
                with patch.object(pasi_provider_router, "providers_available", return_value=["openrouter"]):
                    with patch.object(pasi_provider_router, "call_openrouter", side_effect=fake_openrouter):
                        provider, response = pasi_provider_router.route("task", Path("."), 30.0)

        self.assertEqual((provider, response), ("openrouter", "safe response"))
        self.assertEqual(len(captured), 1)
        self.assertNotIn("PRIVATE-SENTINEL", captured[0])
        self.assertIn("task/contract text only", captured[0])

    def test_opencode_uses_disposable_copy_and_denies_tools(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            (repo / "private.txt").write_text("sensitive", encoding="utf-8")
            with patch("shutil.which", return_value="/usr/bin/opencode"):
                with patch.object(pasi_provider_router.shutil, "copytree") as copytree:
                    with patch.object(pasi_provider_router.subprocess, "run") as run:
                        run.return_value.returncode = 0
                        run.return_value.stdout = "response"
                        run.return_value.stderr = ""
                        result = pasi_provider_router.call_opencode("task", repo, 20.0)

        self.assertEqual(result, "response")
        copy_args = copytree.call_args.args
        self.assertEqual(copy_args[0], repo)
        sandbox = copy_args[1]
        self.assertNotEqual(sandbox, repo)
        command = run.call_args.args[0]
        self.assertEqual(command[:3], ["/usr/bin/opencode", "run", "--standalone"])
        self.assertEqual(command[command.index("--dir") + 1], str(sandbox))
        env = run.call_args.kwargs["env"]
        self.assertEqual(env["OPENCODE_DISABLE_DEFAULT_PLUGINS"], "true")
        self.assertEqual(env["OPENCODE_DISABLE_LSP_DOWNLOAD"], "true")
        for permission in ("edit", "bash", "webfetch", "websearch", "task", "skill", "external_directory", "question"):
            self.assertIn(f'"{permission}": "deny"', env["OPENCODE_PERMISSION"])


if __name__ == "__main__":
    unittest.main()
