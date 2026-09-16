from __future__ import annotations

from automation.orchestrator.execution_schema import ExecutionResult
from automation.orchestrator.state import StateManager


def test_execution_result_round_trips_through_state(tmp_path) -> None:
    state = StateManager(tmp_path / ".ai")
    result = ExecutionResult(
        request_id="req-1",
        task_id="task-1",
        step_id="step-1",
        action="run_simulation",
        status="executed",
        output={"ok": True, "run_id": "sim-1"},
    )

    state.save_execution_result(result)

    assert state.load_execution_result() == {
        "request_id": "req-1",
        "task_id": "task-1",
        "step_id": "step-1",
        "action": "run_simulation",
        "status": "executed",
        "output": {"ok": True, "run_id": "sim-1"},
        "error": None,
    }
