from automation.orchestrator.models import ChatOperation
from automation.orchestrator.operation_state import (
    OPERATION_STATE_SCHEMA_VERSION,
    InvalidOperationState,
    OperationState,
    digest_text,
)


def test_canonical_state_is_versioned_and_bounded() -> None:
    state = OperationState(
        operation_id="op-1",
        operation_type="prompt",
        run_id="run-1",
        task_id="P1.1",
        provider="chatgpt_browser",
        phase="automation",
        attempt=2,
        prompt_digest=digest_text("prompt"),
        verification_status="verified",
        recovery_count=1,
    )

    payload = state.to_dict()

    assert payload["schema_version"] == OPERATION_STATE_SCHEMA_VERSION
    assert payload["prompt_digest"] == digest_text("prompt")
    assert "prompt" not in payload
    assert payload["recovery_count"] == 1


def test_chat_operation_maps_to_canonical_state_without_retaining_transcript() -> None:
    operation = ChatOperation(
        operation_id="op-9",
        operation_type="prompt",
        prompt="secret prompt text",
        status="completed",
        response_text="secret response text",
        response_text_available=True,
    )

    state = OperationState.from_chat_operation(operation.to_dict())

    assert state.operation_id == "op-9"
    assert state.status == "completed"
    assert state.prompt_digest == digest_text("secret prompt text")
    assert state.response_digest == digest_text("secret response text")
    assert "secret prompt text" not in repr(state.to_dict())
    assert "secret response text" not in repr(state.to_dict())


def test_schema_version_must_match() -> None:
    try:
        OperationState.from_mapping(
            {
                "schema_version": OPERATION_STATE_SCHEMA_VERSION + 1,
                "operation_id": "op-1",
                "operation_type": "prompt",
            }
        )
    except InvalidOperationState as exc:
        assert "schema version" in str(exc)
    else:
        raise AssertionError("expected schema version validation failure")
