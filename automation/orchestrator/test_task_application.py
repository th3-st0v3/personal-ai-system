from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from automation.computer_use.contracts import AIResponse

from .state import StateManager
from .task_application import (
    ConfiguredTaskRunFactory,
    TaskRuntimeConfig,
    TaskRuntimeDependencies,
)
from .task_goal import TaskGoal
from .task_planner import StructuredTaskPlanner


class FakeAI:
    provider = "fake"

    def new_session(self) -> str:
        return "fake-session"

    def select_reasoning_mode(self, mode: str) -> None:
        return None

    def submit_prompt(self, prompt: str) -> str:
        return "fake-operation"

    def read_response(self) -> AIResponse:
        return AIResponse(
            response_id="fake-response",
            session_id="session-runner-1",
            provider=self.provider,
            operation_id="fake-operation",
            text='{"stop":true}',
            completion="complete",
            response_available=True,
        )


class TestConfiguredTaskRunFactory(unittest.TestCase):
    def test_create_wires_bounded_runner_and_explicit_goal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = StateManager(Path(directory))
            factory = ConfiguredTaskRunFactory(
                state,
                TaskRuntimeDependencies(ai=FakeAI()),
                TaskRuntimeConfig(project="personal-ai-system"),
                lambda prompt, session: TaskGoal(
                    goal_id="test-goal",
                    required_observation_kinds=("ai_response",),
                ),
            )

            runner = factory.create(runner_id="runner-1", prompt="test task")

            self.assertEqual(runner.runner_id, "runner-1")
            self.assertEqual(runner.worker.control_plane.session.task_id, "runner-1")
            self.assertTrue(runner.worker.control_plane.session.background)
            self.assertEqual(runner.worker.control_plane.session.project, "personal-ai-system")
            self.assertIsInstance(runner.planner, StructuredTaskPlanner)
            assert isinstance(runner.planner, StructuredTaskPlanner)
            self.assertEqual(runner.planner.session.session_id, "session-runner-1")
            self.assertEqual(runner.max_steps, 32)

    def test_config_rejects_invalid_bounds(self) -> None:
        with self.assertRaises(ValueError):
            TaskRuntimeConfig(project="p", max_steps=0)
        with self.assertRaises(ValueError):
            TaskRuntimeConfig(project="p", planner_max_wait_seconds=0)

    def test_factory_requires_explicit_task_goal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = StateManager(Path(directory))
            factory = ConfiguredTaskRunFactory(
                state,
                TaskRuntimeDependencies(ai=FakeAI()),
                TaskRuntimeConfig(project="personal-ai-system"),
                lambda prompt, session: "not-a-goal",  # type: ignore[return-value]
            )

            with self.assertRaises(TypeError):
                factory.create(runner_id="runner-2", prompt="test task")


if __name__ == "__main__":
    unittest.main()
