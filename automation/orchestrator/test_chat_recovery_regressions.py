from pathlib import Path

from automation.orchestrator.bridge import BridgeState
from automation.orchestrator.state import StateManager


def make_bridge(tmp_path: Path) -> BridgeState:
    return BridgeState(StateManager(tmp_path / ".ai"))


def test_browser_reload_failure_is_bounded_and_requeued(tmp_path: Path) -> None:
    bridge = make_bridge(tmp_path)
    operation = bridge.queue_operation("prompt", "preserve this chat")
    claimed = bridge.claim_next_operation()
    assert claimed is not None

    recovered = bridge.fail_operation(
        operation.operation_id,
        "PASI: browser page reloaded during operation; current chat preserved for bounded retry",
    )

    assert recovered is not None
    assert recovered["status"] == "queued"
    assert recovered["retry_count"] == 1
    assert "preserved" in recovered["last_retry_error"]


def test_native_reload_failure_is_also_bounded_and_requeued(tmp_path: Path) -> None:
    bridge = make_bridge(tmp_path)
    operation = bridge.queue_operation("prompt", "preserve native chat")
    bridge.claim_next_operation()

    recovered = bridge.fail_operation(
        operation.operation_id,
        "PASI_NATIVE: browser page reloaded during operation; operation returned to bounded retry path",
    )

    assert recovered is not None
    assert recovered["status"] == "queued"
    assert recovered["retry_count"] == 1


def test_unrelated_provider_failure_is_not_requeued_as_browser_recovery(tmp_path: Path) -> None:
    bridge = make_bridge(tmp_path)
    operation = bridge.queue_operation("prompt", "provider failure")
    bridge.claim_next_operation()

    failed = bridge.fail_operation(
        operation.operation_id,
        "CHAT_USAGE_LIMITED: provider usage is exhausted",
    )

    assert failed is not None
    assert failed["status"] == "failed"
    assert failed["retry_count"] == 0
