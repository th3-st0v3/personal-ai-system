from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Sequence

from .protocol import ChatMessage, ProviderResponse


class OllamaProvider:
    """Small local Ollama adapter; no browser or DOM dependency."""

    name = "ollama"

    def __init__(self, base_url: str | None = None, default_model: str | None = None, timeout: float = 120.0):
        self.base_url = (base_url or os.environ.get("PASI_OLLAMA_URL", "http://127.0.0.1:11434")).rstrip("/")
        self.default_model = default_model or os.environ.get("PASI_OLLAMA_MODEL", "")
        self.timeout = timeout

    def _request(self, path: str, payload: dict[str, object] | None = None) -> dict[str, object]:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + path,
            data=data,
            headers={"Content-Type": "application/json"} if data is not None else {},
            method="POST" if data is not None else "GET",
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            value = json.loads(response.read().decode("utf-8"))
        if not isinstance(value, dict):
            raise RuntimeError("Ollama returned a non-object response")
        return value

    def health(self) -> dict[str, object]:
        try:
            response = urllib.request.urlopen(self.base_url + "/api/tags", timeout=3)
            with response:
                payload = json.loads(response.read().decode("utf-8"))
            models = payload.get("models", []) if isinstance(payload, dict) else []
            return {"available": True, "provider": self.name, "models": models}
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            return {"available": False, "provider": self.name, "reason": str(exc)[:300]}

    def generate(self, messages: Sequence[ChatMessage], *, model: str | None = None) -> ProviderResponse:
        selected_model = model or self.default_model
        if not selected_model:
            raise ValueError("PASI_OLLAMA_MODEL or an explicit model is required")
        started = time.perf_counter()
        payload = {
            "model": selected_model,
            "messages": [{"role": message.role, "content": message.content} for message in messages],
            "stream": False,
        }
        response = self._request("/api/chat", payload)
        message = response.get("message")
        text = message.get("content") if isinstance(message, dict) else None
        if not isinstance(text, str):
            raise RuntimeError("Ollama response did not contain message.content")
        return ProviderResponse(
            provider=self.name,
            model=selected_model,
            text=text,
            latency_ms=(time.perf_counter() - started) * 1000,
        )
