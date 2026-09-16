from automation.orchestrator.state import StateManager


def test_retry_state_round_trips(tmp_path) -> None:
    state = StateManager(tmp_path / ".ai")
    value = {
        "task_id": "task-1",
        "attempt": 2,
        "replans": 2,
        "max_replans": 2,
        "source": "testing",
        "reason": "A test failed.",
        "details": "pytest -q -> exit 1",
    }

    state.save_retry_state(value)

    assert state.load_retry_state() == value
