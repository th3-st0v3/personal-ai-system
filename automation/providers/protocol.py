from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str


@dataclass(frozen=True)
class ProviderResponse:
    provider: str
    model: str
    text: str
    latency_ms: float


class ModelProvider(Protocol):
    name: str

    def health(self) -> dict[str, object]: ...

    def generate(self, messages: Sequence[ChatMessage], *, model: str | None = None) -> ProviderResponse: ...
