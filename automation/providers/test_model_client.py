from __future__ import annotations

import unittest

from .model_client import ProviderModelClient
from .protocol import ChatMessage, ProviderResponse


class FakeProvider:
    name = "fake"

    def __init__(self, text: str = "ok") -> None:
        self.text = text
        self.calls: list[tuple[list[ChatMessage], str | None]] = []

    def health(self) -> dict[str, object]:
        return {"available": True, "provider": self.name}

    def generate(self, messages, *, model=None) -> ProviderResponse:
        self.calls.append((list(messages), model))
        return ProviderResponse(self.name, model or "fake-model", self.text, 1.0)


class TestProviderModelClient(unittest.TestCase):
    def test_complete_delegates_to_provider(self) -> None:
        provider = FakeProvider("structured response")
        client = ProviderModelClient(provider, model="coder")
        self.assertEqual(client.complete("plan this"), "structured response")
        self.assertEqual(provider.calls[0][0][0], ChatMessage("user", "plan this"))
        self.assertEqual(provider.calls[0][1], "coder")

    def test_complete_rejects_empty_prompt(self) -> None:
        with self.assertRaises(ValueError):
            ProviderModelClient(FakeProvider()).complete(" ")

    def test_complete_rejects_empty_provider_output(self) -> None:
        with self.assertRaises(RuntimeError):
            ProviderModelClient(FakeProvider(" ")).complete("plan")


if __name__ == "__main__":
    unittest.main()
