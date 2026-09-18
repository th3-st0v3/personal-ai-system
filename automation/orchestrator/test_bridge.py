from pathlib import Path

import pytest

from automation.orchestrator.bridge import BridgeState
from automation.orchestrator.operation_lifecycle import InvalidOperationTransition
from automation.orchestrator.state import StateManager


def make_bridge(tmp_path: Path) -> BridgeState:
    return BridgeState(
        StateManager(tmp_path / ".ai")
    )


def test_operation_lifecycle(tmp_path: Path) -> None:
    bridge = make_bridge(tmp_path)

    operation = bridge.queue_operation(
        operation_type="test",
        prompt="PASI lifecycle test",
    )

    initial = bridge.get_operation(operation.operation_id)
    assert initial is not None
    assert initial["status"] == "queued"

    status = bridge.get_status()
    assert status["queue_size"] == 1
    assert status["history_size"] == 1
    assert status["counts"] == {"queued": 1}

    claimed = bridge.claim_next_operation()

    assert claimed is not None
    assert claimed["operation_id"] == operation.operation_id
    assert claimed["status"] == "claimed"

    status = bridge.get_status()
    assert status["queue_size"] == 1
    assert status["counts"] == {"claimed": 1}

    generating = bridge.heartbeat(
        operation.operation_id
    )

    assert generating is not None
    assert generating["status"] == "generating"

    status = bridge.get_status()
    assert status["queue_size"] == 1
    assert status["counts"] == {"generating": 1}

    completed = bridge.complete_operation(
        operation.operation_id,
        chat_url="https://chatgpt.com/c/test",
        response_text="PASI response completed successfully.",
        response_text_available=True,
    )

    assert completed is not None
    assert completed["status"] == "completed"
    assert (
        completed["chat_url"]
        == "https://chatgpt.com/c/test"
    )
    assert (
        completed["response_text"]
        == "PASI response completed successfully."
    )
    assert completed["response_text_available"] is True
    final = bridge.get_operation(operation.operation_id)
    assert final is not None
    assert final["status"] == "completed"
    assert final["response_text_available"] is True

    status = bridge.get_status()
    assert status["queue_size"] == 0
    assert status["history_size"] == 1
    assert status["counts"] == {"completed": 1}


def test_response_observation_survives_later_browser_state_updates(tmp_path: Path) -> None:
    bridge = make_bridge(tmp_path)
    operation = bridge.queue_operation("prompt", "preserve response")
    response_observation = {
        "schema_version": "pasi-native-chromium-v1",
        "captured_at": "2026-09-18T12:00:00+00:00",
        "data": {
            "kind": "chatgpt_response",
            "active_operation_id": operation.operation_id,
            "chat_url": "https://chatgpt.com/c/example",
            "response_text": "durable answer",
            "response_text_available": True,
        },
    }
    state_observation = {
        "schema_version": "pasi-native-chromium-v1",
        "captured_at": "2026-09-18T12:00:01+00:00",
        "data": {"kind": "chatgpt_state", "chat_url": "https://chatgpt.com/c/example"},
    }

    bridge.save_browser_observation(response_observation)
    bridge.save_browser_observation(state_observation)

    saved = bridge.get_browser_response()
    assert saved == response_observation
    assert bridge.get_browser_observation() == state_observation


def test_completed_response_text_is_bounded(tmp_path: Path) -> None:
    bridge = make_bridge(tmp_path)
    operation = bridge.queue_operation("test", "bounded")
    bridge.claim_next_operation()
    bridge.heartbeat(operation.operation_id)

    completed = bridge.complete_operation(
        operation.operation_id,
        response_text="x" * 60_000,
        response_text_available=True,
    )

    assert completed is not None
    assert len(completed["response_text"]) == 50_000
    assert completed["response_text_available"] is True


def test_completed_empty_response_is_not_available(tmp_path: Path) -> None:
    bridge = make_bridge(tmp_path)
    operation = bridge.queue_operation("test", "empty")
    bridge.claim_next_operation()
    bridge.heartbeat(operation.operation_id)

    completed = bridge.complete_operation(
        operation.operation_id,
        response_text="   ",
        response_text_available=True,
    )

    assert completed is not None
    assert completed["response_text_available"] is False


def test_failed_operation_is_not_active(
    tmp_path: Path,
) -> None:
    bridge = make_bridge(tmp_path)

    operation = bridge.queue_operation(
        operation_type="test",
        prompt="PASI failure test",
    )

    claimed = bridge.claim_next_operation()

    assert claimed is not None

    failed = bridge.fail_operation(
        operation.operation_id,
        error="intentional test failure",
    )

    assert failed is not None
    assert failed["status"] == "failed"
    assert (
        failed["error"]
        == "intentional test failure"
    )

    status = bridge.get_status()
    assert status["queue_size"] == 0
    assert status["history_size"] == 1
    assert status["counts"] == {"failed": 1}


def test_claim_only_returns_queued_operations(
    tmp_path: Path,
) -> None:
    bridge = make_bridge(tmp_path)

    first = bridge.queue_operation(
        operation_type="test",
        prompt="first",
    )
    second = bridge.queue_operation(
        operation_type="test",
        prompt="second",
    )

    claimed = bridge.claim_next_operation()

    assert claimed is not None
    assert claimed["operation_id"] == first.operation_id

    claimed_again = bridge.claim_next_operation()

    assert claimed_again is not None
    assert (
        claimed_again["operation_id"]
        == second.operation_id
    )

    assert bridge.claim_next_operation() is None

    status = bridge.get_status()
    assert status["queue_size"] == 2
    assert status["history_size"] == 2
    assert status["counts"] == {"claimed": 2}


def test_missing_operation_returns_none(tmp_path: Path) -> None:
    bridge = make_bridge(tmp_path)
    assert bridge.get_operation("op-does-not-exist") is None


def test_new_chat_operation_can_have_empty_prompt(tmp_path: Path) -> None:
    bridge = make_bridge(tmp_path)
    operation = bridge.queue_operation("new_chat", "")
    assert operation.operation_type == "new_chat"
    assert operation.prompt == ""


def test_completed_operation_cannot_return_to_generating(tmp_path: Path) -> None:
    bridge = make_bridge(tmp_path)
    operation = bridge.queue_operation("test", "done")
    bridge.claim_next_operation()
    bridge.heartbeat(operation.operation_id)
    bridge.complete_operation(operation.operation_id)

    with pytest.raises(InvalidOperationTransition):
        bridge.heartbeat(operation.operation_id)

    final = bridge.get_operation(operation.operation_id)
    assert final is not None
    assert final["status"] == "completed"


def test_failed_operation_cannot_be_completed_later(tmp_path: Path) -> None:
    bridge = make_bridge(tmp_path)
    operation = bridge.queue_operation("test", "fail")
    bridge.claim_next_operation()
    bridge.fail_operation(operation.operation_id, "failure")

    with pytest.raises(InvalidOperationTransition):
        bridge.complete_operation(operation.operation_id)

    final = bridge.get_operation(operation.operation_id)
    assert final is not None
    assert final["status"] == "failed"


def test_heartbeat_requires_claimed_or_generating_state(tmp_path: Path) -> None:
    bridge = make_bridge(tmp_path)
    operation = bridge.queue_operation("test", "queued")

    with pytest.raises(InvalidOperationTransition):
        bridge.heartbeat(operation.operation_id)

    final = bridge.get_operation(operation.operation_id)
    assert final is not None
    assert final["status"] == "queued"
