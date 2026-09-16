from pathlib import Path

from automation.orchestrator.bridge import BridgeState
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

    assert bridge.get_operation(operation.operation_id)["status"] == "queued"

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
    )

    assert completed is not None
    assert completed["status"] == "completed"
    assert (
        completed["chat_url"]
        == "https://chatgpt.com/c/test"
    )
    assert bridge.get_operation(operation.operation_id)["status"] == "completed"

    status = bridge.get_status()
    assert status["queue_size"] == 0
    assert status["history_size"] == 1
    assert status["counts"] == {"completed": 1}


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


def test_new_chat_operation_can_have_empty_prompt(tmp_path: Path) -> None:
    bridge = make_bridge(tmp_path)
    operation = bridge.queue_operation("new_chat", "")
    assert operation.operation_type == "new_chat"
    assert operation.prompt == ""
