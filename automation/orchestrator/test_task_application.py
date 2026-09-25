from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from automation.providers.protocol import ChatMessage, ProviderResponse

from .state import StateManager
from .task_application import (
    ConfiguredTaskRunFactory,
    TaskRuntimeConfig,
    TaskRuntimeDependencies,
)
from .task_goal import TaskGoal
from .task_planner import StructuredTaskPlanner


class FakeModel:
    name = "fake"

    def health(self) -> dict[str, object]:
        return {"available": True, "provider": self.name}

    def generate(self, messages, *, model=None) -> ProviderResponse:
        assert messages and isinstance(messages[0], ChatMessage)
        return ProviderResponse(
            provider=self.name,
            model=model or "fake-model",
            text='{"stop":true}',
            latency_ms=0.1,
        )

