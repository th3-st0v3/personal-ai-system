from __future__ import annotations

from typing import Protocol, Sequence

from .contracts import (
    AIResponse,
    ActionProposal,
    CompletionState,
    ContextPackage,
    Observation,
)


class AIAdapter(Protocol):
    """Provider-independent boundary for AI sessions."""

    provider: str

    def new_session(self) -> str: ...

    def select_reasoning_mode(self, mode: str) -> None: ...

    def submit_prompt(self, prompt: str) -> str: ...

    def read_response(self) -> AIResponse: ...


class CompletionDetector(Protocol):
    """Determines whether an AI provider has finished generating."""

    def detect(self, observations: Sequence[Observation]) -> CompletionState: ...


class ComputerAdapter(Protocol):
    """Semantic computer/desktop surface; concrete UI mechanics stay outside core."""

    def observe(self) -> Observation: ...

    def execute(self, action: ActionProposal) -> Observation: ...


class IDEAdapter(Protocol):
    """Read-first IDE boundary for files, search, diagnostics, and bounded commands."""

    def observe(self) -> Observation: ...

    def read_file(self, path: str) -> Observation: ...

    def search(self, query: str) -> Observation: ...

    def diagnostics(self) -> Observation: ...


class GitHubAdapter(Protocol):
    """Repository boundary that may use API/connector or UI implementations."""

    def observe(self) -> Observation: ...

    def execute(self, action: ActionProposal) -> Observation: ...


class ResearchAdapter(Protocol):
    """Read-only external research boundary."""

    def search(self, query: str) -> Observation: ...

    def read(self, source: str) -> Observation: ...


class ContextCollector(Protocol):
    """Assembles task-scoped evidence without coupling to a provider."""

    def collect(self, objective: str, observations: Sequence[Observation]) -> ContextPackage: ...
