from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from automation.orchestrator.context_schema import ContextPackage
from automation.orchestrator.main import main
from automation.orchestrator.state import StateManager


def make_fake_config(
    project_root: Path,
    ai_dir: Path,
):
    return type(
        "Config",
        (),
        {
            "project_root": project_root,
            "ai_dir": ai_dir,
        },
    )()


def make_fake_test_runner():
    class FakeTests:
        def detect_commands(self):
            return []

        def run_project_tests(self):
            return []

    return FakeTests()


def run_main(
    project_root: Path,
    ai_dir: Path,
    objective: str | None = None,
) -> None:
    fake_config = make_fake_config(project_root, ai_dir)
    fake_tests = make_fake_test_runner()

    with patch(
        "automation.orchestrator.main.CONFIG",
        fake_config,
    ), patch(
        "automation.orchestrator.main.TestRunner",
        return_value=fake_tests,
    ), patch(
        "automation.orchestrator.main.ensure_runtime_directories",
    ):
        if objective is None:
            main()
        else:
            main(objective)


def test_main_builds_and_persists_context_package(
    tmp_path: Path,
) -> None:
    ai_dir = tmp_path / ".ai"
    ai_dir.mkdir()

    project_root = tmp_path / "project"
    project_root.mkdir()

    run_main(
        project_root,
        ai_dir,
        "Make the login button work.",
    )

    state = StateManager(ai_dir)
    payload = state.load_context_package()

    assert payload["schema_version"] == "1.0"
    assert (
        payload["objective"]["primary"]
        == "Make the login button work."
    )

    package = ContextPackage.model_validate(payload)

    assert (
        package.objective.primary
        == "Make the login button work."
    )
    assert package.project.name == "project"

    raw = state.context_package_path.read_text(
        encoding="utf-8",
    )
    assert json.loads(raw) == payload


def test_main_uses_default_objective_when_called_without_argument(
    tmp_path: Path,
) -> None:
    ai_dir = tmp_path / ".ai"
    ai_dir.mkdir()

    project_root = tmp_path / "project"
    project_root.mkdir()

    run_main(
        project_root,
        ai_dir,
    )

    payload = StateManager(ai_dir).load_context_package()

    assert (
        payload["objective"]["primary"]
        == "Inspect the current project state."
    )


def test_main_marks_precheck_complete(
    tmp_path: Path,
) -> None:
    ai_dir = tmp_path / ".ai"
    ai_dir.mkdir()

    project_root = tmp_path / "project"
    project_root.mkdir()

    run_main(
        project_root,
        ai_dir,
        "Verify precheck integration.",
    )

    project_state = StateManager(ai_dir).load_project_state()

    assert project_state["status"] == "idle"
    assert (
        project_state["current_phase"]
        == "context_ready"
    )



def test_main_creates_and_advances_current_task(
    tmp_path: Path,
) -> None:
    ai_dir = tmp_path / ".ai"
    ai_dir.mkdir()

    project_root = tmp_path / "project"
    project_root.mkdir()

    run_main(
        project_root,
        ai_dir,
        "Make the login button work.",
    )

    state = StateManager(ai_dir)
    task = state.load_current_task()
    project_state = state.load_project_state()

    assert task["objective"] == "Make the login button work."
    assert task["feature"] == "orchestrator"
    assert task["status"] == "ready"
    assert task["phase"] == "context_ready"
    assert task["attempt"] == 0

    assert project_state["current_task_id"] == task["task_id"]
    assert project_state["current_feature"] == "orchestrator"
    assert project_state["current_phase"] == "context_ready"


def test_main_uses_same_task_for_context_objective(
    tmp_path: Path,
) -> None:
    ai_dir = tmp_path / ".ai"
    ai_dir.mkdir()

    project_root = tmp_path / "project"
    project_root.mkdir()

    objective = "Verify the authentication flow."

    run_main(
        project_root,
        ai_dir,
        objective,
    )

    state = StateManager(ai_dir)
    task = state.load_current_task()
    context = state.load_context_package()

    assert task["objective"] == objective
    assert context["objective"]["primary"] == task["objective"]
