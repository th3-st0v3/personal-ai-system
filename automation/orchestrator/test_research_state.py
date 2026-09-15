from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from automation.orchestrator.research_schema import (
    ResearchFinding,
    ResearchObservation,
)
from automation.orchestrator.research_state import ResearchState
from automation.orchestrator.state import StateManager


def make_state() -> ResearchState:
    return ResearchState(task_id="task_test_001")


def make_observation() -> ResearchObservation:
    return ResearchObservation(
        observation_id="obs-001",
        subject="Engineering simulator",
        aspect="results workflow",
        statement="Results are presented separately from input configuration.",
        source_ref="source:simulator",
    )


def make_finding() -> ResearchFinding:
    return ResearchFinding(
        finding_id="finding-001",
        statement="Simulation configuration should remain distinct from global settings.",
        supporting_observations=["obs-001"],
        design_implications=[
            "Keep simulation-run state separate from application preferences.",
        ],
    )


def test_research_state_starts_empty() -> None:
    state = make_state()

    assert state.task_id == "task_test_001"
    assert state.observations == []
    assert state.findings == []
    assert state.updated_at.tzinfo is not None


def test_research_state_adds_observation() -> None:
    state = make_state()
    before = state.updated_at

    state.add_observation(make_observation())

    assert len(state.observations) == 1
    assert state.observations[0].observation_id == "obs-001"
    assert state.updated_at >= before


def test_research_state_adds_finding() -> None:
    state = make_state()

    state.add_finding(make_finding())

    assert len(state.findings) == 1
    assert state.findings[0].finding_id == "finding-001"


def test_research_state_can_contain_both_observations_and_findings() -> None:
    state = make_state()

    state.add_observation(make_observation())
    state.add_finding(make_finding())

    assert len(state.observations) == 1
    assert len(state.findings) == 1
    assert state.findings[0].supporting_observations == ["obs-001"]


def test_research_state_requires_task_id() -> None:
    with pytest.raises(ValidationError):
        ResearchState(task_id="")


def test_research_state_serializes_to_json() -> None:
    state = make_state()
    state.add_observation(make_observation())
    state.add_finding(make_finding())

    payload = state.model_dump(mode="json")

    assert payload["task_id"] == "task_test_001"
    assert payload["observations"][0]["observation_id"] == "obs-001"
    assert payload["findings"][0]["finding_id"] == "finding-001"

    json.dumps(payload)


def test_state_manager_persists_and_loads_research_state(
    tmp_path: Path,
) -> None:
    manager = StateManager(tmp_path / ".ai")
    state = make_state()

    state.add_observation(make_observation())
    state.add_finding(make_finding())

    manager.save_research_state(state)

    payload = manager.load_research_state()

    assert payload["task_id"] == "task_test_001"
    assert payload["observations"][0]["statement"].startswith(
        "Results are presented"
    )
    assert payload["findings"][0]["design_implications"] == [
        "Keep simulation-run state separate from application preferences.",
    ]


def test_persisted_research_state_round_trips_through_model(
    tmp_path: Path,
) -> None:
    manager = StateManager(tmp_path / ".ai")
    state = make_state()

    state.add_observation(make_observation())
    state.add_finding(make_finding())

    manager.save_research_state(state)

    restored = ResearchState.model_validate(
        manager.load_research_state()
    )

    assert restored == state


def test_research_state_file_is_valid_json(
    tmp_path: Path,
) -> None:
    manager = StateManager(tmp_path / ".ai")
    state = make_state()

    manager.save_research_state(state)

    raw = manager.research_state_path.read_text(
        encoding="utf-8"
    )

    json.loads(raw)
