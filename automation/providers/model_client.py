from __future__ import annotations

from .protocol import ChatMessage, ModelProvider


class ProviderModelClient:
    """Adapt the PASI model-provider contract to the planner's complete() seam."""

    def __init__(self, provider: ModelProvider, *, model: str | None = None) -> None:
        self.provider = provider
        self.model = model

    def complete(self, prompt: str) -> str:
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt is required")
        response = self.provider.generate(
            [ChatMessage(role="user", content=prompt)],
            model=self.model,
        )
        if not response.text.strip():
            raise RuntimeError("model provider returned empty text")
        return response.text


__all__ = ["ProviderModelClient"]
