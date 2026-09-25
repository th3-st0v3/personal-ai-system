from __future__ import annotations

import json

import pytest

from automation.computer_use.contracts import Observation, Session
from automation.orchestrator.task_goal import EvidenceGoalChecker, TaskGoal
from automation.orchestrator.task_planner import AIAdapterModelClient, StructuredTaskPlanner


class StubModel:
    def __init__(self, payload: object) -> None:
        self.payload = json.dumps(payload)
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.payload

