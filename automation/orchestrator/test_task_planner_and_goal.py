from __future__ import annotations

import json

import pytest

from automation.computer_use.contracts import AIResponse, Observation, Session
from automation.orchestrator.task_goal import EvidenceGoalChecker, TaskGoal
from automation.orchestrator.task_planner import AIAdapterModelClient, StructuredTaskPlanner


class StubModel:
    def __init__(self, payload: object) -> None:
        self.payload = json.dumps(payload)
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.payload


class StubAdapter:
    provider = "stub"

    def __init__(self, responses: list[AIResponse]) -> None:
        self.responses = list(responses)
        self.new_sessions = 0
        self.submitted_prompts: list[str] = []

    def new_session(self) -> str:
        self.new_sessions += 1
        return "operation-1"

    def select_reasoning_mode(self, mode: str) -> None:
        raise AssertionError("reasoning mode should not be selected by this client")

    def submit_prompt(self, prompt: str) -> str:
        self.submitted_prompts.append(prompt)
        return "operation-2"

    def read_response(self) -> AIResponse:
        if not self.responses:
            raise AssertionError("no stub response remains")
        return self.responses.pop(0)


def session() -> Session:
    return Session(session_id="session-1", task_id="task-1", project="project")


def test_structured_planner_accepts_policy_consistent_action() -> None:
    model = StubModel(
        {
            "stop": False,
            "action": {
                "action_id": "a1",
                "session_id": "session-1",
                "target": "repo",
                "action": "github_read",
                "parameters": {"path": "README.md"},
                "reason": "inspect evidence",
                "risk": "safe",
            },
        }
    )
    planner = StructuredTaskPlanner(session(), model)

    action = planner.plan([])

    assert action is not None
    assert action.action_id == "a1"
    assert action.effective_risk() == "safe"
    assert "Return JSON only." in model.prompts[0]


def test_structured_planner_rejects_session_confusion() -> None:
    model = StubModel(
        {
            "stop": False,
            "action": {
                "action_id": "a1",
                "session_id": "other-session",
                "target": "repo",
                "action": "github_read",
            },
        }
    )

    with pytest.raises(ValueError, match="different control session"):
        StructuredTaskPlanner(session(), model).plan([])


def test_structured_planner_rejects_risk_mismatch() -> None:
    model = StubModel(
        {
            "stop": False,
            "action": {
                "action_id": "a1",
                "session_id": "session-1",
                "target": "desktop",
                "action": "desktop_ui",
                "risk": "safe",
            },
        }
    )

    with pytest.raises(ValueError, match="does not match"):
        StructuredTaskPlanner(session(), model).plan([])


def test_structured_planner_never_treats_stop_as_completion() -> None:
    model = StubModel({"stop": True})

    decision = StructuredTaskPlanner(session(), model).decide([])

    assert decision.stop_requested is True
    assert decision.action is None


def test_structured_planner_rejects_non_json() -> None:
    class BadModel:
        def complete(self, prompt: str) -> str:
            return "not json"

    with pytest.raises(ValueError, match="invalid JSON"):
        StructuredTaskPlanner(session(), BadModel()).plan([])


def test_structured_planner_bounds_model_output() -> None:
    model = StubModel({"stop": False, "action": {"action_id": "a1"}})
    planner = StructuredTaskPlanner(session(), model, max_model_output_chars=10)

    with pytest.raises(ValueError, match="output exceeded"):
        planner.plan([])


def test_structured_planner_bounds_parameters() -> None:
    model = StubModel(
        {
            "stop": False,
            "action": {
                "action_id": "a1",
                "session_id": "session-1",
                "target": "repo",
                "action": "github_read",
                "parameters": {"payload": "x" * 100},
            },
        }
    )
    planner = StructuredTaskPlanner(session(), model, max_parameters_chars=20)

    with pytest.raises(ValueError, match="parameters exceeded"):
        planner.plan([])


def test_ai_adapter_model_client_creates_session_once_and_waits_for_completion() -> None:
    adapter = StubAdapter(
        [
            AIResponse("r1", "session-1", "stub", "op-1", "", "generating"),
            AIResponse("r2", "session-1", "stub", "op-1", "answer", "complete", True),
        ]
    )
    client = AIAdapterModelClient(adapter, poll_interval_seconds=0.001, max_wait_seconds=1)

    assert client.complete("hello") == "answer"
    assert adapter.new_sessions == 1
    assert adapter.submitted_prompts == ["hello"]


def test_ai_adapter_model_client_rejects_non_success_completion() -> None:
    adapter = StubAdapter(
        [AIResponse("r1", "session-1", "stub", "op-1", "", "error")]
    )
    client = AIAdapterModelClient(adapter)

    with pytest.raises(RuntimeError, match="'error'"):
        client.complete("hello")


def observation(kind: str, source: str, **data: object) -> Observation:
    return Observation(
        observation_id=f"obs-{kind}-{source}",
        session_id="session-1",
        source=source,
        kind=kind,
        data=data,
    )


def test_evidence_goal_requires_explicit_requirements() -> None:
    checker = EvidenceGoalChecker(
        TaskGoal(
            "goal-1",
            required_observation_kinds=("diagnostic", "result"),
            required_sources=("vscode", "executor"),
            minimum_verified_observations=1,
        )
    )

    incomplete = checker.check((observation("diagnostic", "vscode"),))
    assert incomplete.status == "incomplete"
    assert "observation kind 'result' is missing" in incomplete.reason

    complete = checker.check(
        (
            observation("diagnostic", "vscode"),
            observation("result", "executor", verification_status="verified"),
        )
    )
    assert complete.complete is True
    assert complete.status == "complete"


def test_evidence_goal_predicate_failures_are_non_fatal_but_unsatisfied() -> None:
    checker = EvidenceGoalChecker(
        TaskGoal(
            "goal-2",
            required_predicates={"pressure-safe": lambda item: item.data.get("pressure") == 100},
        )
    )

    result = checker.check((observation("measurement", "sensor", pressure=99),))
    assert result.status == "incomplete"
    assert "pressure-safe" in result.reason
