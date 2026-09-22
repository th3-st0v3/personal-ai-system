"""Provider and local-model capability discovery without exposing credentials."""
from __future__ import annotations

import os
import urllib.error
import urllib.request
import json


_PROVIDER_ENV = {
    "openrouter": "OPENROUTER_API_KEY",
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "groq": "GROQ_API_KEY",
    "perplexity": "PERPLEXITY_API_KEY",
}


def _ollama_models(timeout: float = 1.5) -> tuple[bool, list[str], str | None]:
    base = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    request = urllib.request.Request(base + "/api/tags", headers={"Accept": "application/json"}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read(1_000_001).decode("utf-8"))
    except (OSError, TimeoutError, ValueError, urllib.error.URLError) as exc:
        return False, [], type(exc).__name__
    models = payload.get("models") if isinstance(payload, dict) else None
    names = [
        item["name"].strip()
        for item in (models or [])
        if isinstance(item, dict) and isinstance(item.get("name"), str) and item["name"].strip()
    ]
    return True, names[:100], None


def capabilities() -> dict[str, object]:
    reachable, models, error_type = _ollama_models()
    configured = {provider: bool(os.environ.get(env_name, "").strip()) for provider, env_name in _PROVIDER_ENV.items()}
    selected_ollama = os.environ.get("OLLAMA_MODEL", "").strip()
    return {
        "local": {
            "ollama": {
                "reachable": reachable,
                "models": models,
                "selected_model": selected_ollama or (models[0] if models else None),
                "error_type": error_type,
            }
        },
        "hosted": [
            {"provider": provider, "configured": configured[provider], "credential_env": env_name}
            for provider, env_name in _PROVIDER_ENV.items()
        ],
        "credential_policy": "Secrets are never returned to the browser; only configuration presence is reported.",
    }


__all__ = ["capabilities"]
