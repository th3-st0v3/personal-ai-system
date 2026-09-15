from __future__ import annotations

import json
from pathlib import Path

from automation.orchestrator.context_builder import ContextBuilder
from automation.orchestrator.context_schema import (
    ObjectiveContext,
)
from automation.orchestrator.git_manager import GitManager
from automation.orchestrator.state import StateManager


def make_builder(tmp_path: Path) -> ContextBuilder:
    ai_dir = tmp_path / ".ai"
    ai_dir.mkdir()

    return ContextBuilder(
        project_root=tmp_path,
        git=GitManager(tmp_path),
        state=StateManager(ai_dir),
    )


def test_builder_produces_valid_context_without_optional_evidence(
    tmp_path: Path,
) -> None:
    builder = make_builder(tmp_path)

    package = builder.build(
        objective=ObjectiveContext(
            primary="Make the login button work.",
            success_criteria=["Login succeeds."],
        )
    )

    assert package.objective.primary == "Make the login button work."
    assert package.browser.available is False
    assert package.memory.query == "Make the login button work."
    assert package.execution_policy.allowed_actions == []
    assert package.git_wsl.sync_state == "UNKNOWN"
    assert package.tests.status == "unknown"


def test_builder_reads_persisted_test_result(
    tmp_path: Path,
) -> None:
    builder = make_builder(tmp_path)

    result = {
        "success": True,
        "command": ["python", "-m", "pytest", "-v"],
        "return_code": 0,
        "stdout": "8 passed in 0.10s",
        "stderr": "",
        "duration_seconds": 0.1,
    }

    builder.state.save_test_results(result)

    package = builder.build(
        objective=ObjectiveContext(
            primary="Verify the current implementation.",
        )
    )

    assert package.tests.status == "passed"
    assert package.tests.frameworks == ["pytest"]
    assert package.tests.summary.passed == 8
    assert package.tests.summary.failed == 0


def test_builder_reads_browser_state(
    tmp_path: Path,
) -> None:
    builder = make_builder(tmp_path)

    browser_result = {
        "url": "http://localhost:3000/login",
        "title": "Login",
        "type": "webpage",
        "observation_id": "obs-123",
    }

    builder.state.save_browser_results(browser_result)

    package = builder.build(
        objective=ObjectiveContext(
            primary="Verify the login page.",
        )
    )

    assert package.browser.available is True
    assert package.browser.url == "http://localhost:3000/login"
    assert package.browser.page is not None
    assert package.browser.page.title == "Login"
    assert package.browser.observation_id == "obs-123"


def test_builder_marks_changed_files_as_relevant(
    tmp_path: Path,
) -> None:
    builder = make_builder(tmp_path)

    assert builder.git.run("init").success

    assert builder.git.run(
        "config",
        "user.email",
        "pasi-test@example.invalid",
    ).success

    assert builder.git.run(
        "config",
        "user.name",
        "PASI Test",
    ).success

    example = tmp_path / "example.py"
    example.write_text(
        "print('baseline')\\n",
        encoding="utf-8",
    )

    assert builder.git.run("add", "example.py").success
    assert builder.git.run(
        "commit",
        "-m",
        "baseline",
    ).success

    example.write_text(
        "print('changed')\\n",
        encoding="utf-8",
    )

    package = builder.build(
        objective=ObjectiveContext(
            primary="Inspect the current project state.",
        )
    )

    assert any(
        item.path == "example.py"
        for item in package.files.relevant
    )

def test_context_is_json_serializable(
    tmp_path: Path,
) -> None:
    builder = make_builder(tmp_path)

    package = builder.build(
        objective=ObjectiveContext(
            primary="Test serialization.",
        )
    )

    payload = package.to_context_dict()

    assert payload["schema_version"] == "1.0"
    json.dumps(payload)
