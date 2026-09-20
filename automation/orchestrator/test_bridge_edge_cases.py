from __future__ import annotations

import json
import threading
from http.client import HTTPConnection
from pathlib import Path
import pytest
from typing import Any

from automation.orchestrator.bridge import BridgeHTTPServer, BridgeRequestHandler, BridgeState
from automation.orchestrator.state import StateManager


@pytest.fixture(autouse=True)
def bridge_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PASI_BRIDGE_TOKEN", "test-bridge-token")


def make_bridge(tmp_path: Path) -> BridgeState:
    return BridgeState(StateManager(tmp_path / ".ai"))


def post_json(
    server: BridgeHTTPServer,
    path: str,
    payload: dict[str, object],
) -> tuple[int, dict[str, Any]]:
    connection = HTTPConnection("127.0.0.1", server.server_address[1], timeout=2)
    try:
        connection.request(
            "POST",
            path,
            body=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": "Bearer test-bridge-token"},
        )
        response = connection.getresponse()
        body = json.loads(response.read().decode("utf-8"))
        return response.status, body
    finally:
        connection.close()


def start_server(
    bridge: BridgeState,
) -> tuple[BridgeHTTPServer, threading.Thread]:
    server = BridgeHTTPServer(("127.0.0.1", 0), BridgeRequestHandler)
    server.bridge_state = bridge
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def stop_server(server: BridgeHTTPServer, thread: threading.Thread) -> None:
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)
    assert not thread.is_alive()


def test_http_finished_rejects_prompt_without_verified_response(
    tmp_path: Path,
) -> None:
    bridge = make_bridge(tmp_path)
    server, thread = start_server(bridge)

    try:
        operation = bridge.queue_operation("prompt", "response required")
        bridge.claim_next_operation()
        bridge.heartbeat(operation.operation_id)

        status, body = post_json(
            server,
            "/chat/finished",
            {
                "operation_id": operation.operation_id,
                "chat_url": "https://chatgpt.com/c/no-response",
                "response_text": "   ",
                "response_text_available": True,
            },
        )

        assert status == 409
        assert body["error"] == "Prompt completion requires verified nonblank response_text."
        persisted = bridge.get_operation(operation.operation_id)
        assert persisted is not None
        assert persisted["status"] == "generating"
        assert persisted.get("response_text_available") is False
    finally:
        stop_server(server, thread)


def test_http_finished_rejects_terminal_operation_transition(
    tmp_path: Path,
) -> None:
    bridge = make_bridge(tmp_path)
    server, thread = start_server(bridge)

    try:
        operation = bridge.queue_operation("prompt", "terminal")
        bridge.claim_next_operation()
        bridge.heartbeat(operation.operation_id)

        status, body = post_json(
            server,
            "/chat/finished",
            {
                "operation_id": operation.operation_id,
                "chat_url": "https://chatgpt.com/c/terminal",
                "response_text": "first completion",
                "response_text_available": True,
            },
        )
        assert status == 200
        assert body["operation"]["status"] == "completed"

        retry_status, retry_body = post_json(
            server,
            "/chat/finished",
            {
                "operation_id": operation.operation_id,
                "chat_url": "https://chatgpt.com/c/terminal",
                "response_text": "",
                "response_text_available": False,
            },
        )

        assert retry_status == 200
        assert retry_body["operation"]["status"] == "completed"
        persisted = bridge.get_operation(operation.operation_id)
        assert persisted is not None
        assert persisted["status"] == "completed"
        assert persisted["response_text"] == "first completion"
    finally:
        stop_server(server, thread)


def test_http_finished_accepts_persisted_verified_response_when_retry_payload_is_blank(
    tmp_path: Path,
) -> None:
    bridge = make_bridge(tmp_path)
    server, thread = start_server(bridge)

    try:
        operation = bridge.queue_operation("prompt", "response observed before acknowledgement")
        bridge.claim_next_operation()
        bridge.heartbeat(operation.operation_id)

        observation = {
            "schema_version": "pasi-native-chromium-v2",
            "captured_at": 123.0,
            "data": {
                "kind": "chatgpt_response",
                "active_operation_id": operation.operation_id,
                "chat_url": "https://chatgpt.com/c/persisted-response",
                "response_text": "verified browser response",
                "response_text_available": True,
            },
        }
        bridge.save_browser_observation(observation)

        status, body = post_json(
            server,
            "/chat/finished",
            {
                "operation_id": operation.operation_id,
                "chat_url": "https://chatgpt.com/c/persisted-response",
                "response_text": "",
                "response_text_available": False,
            },
        )

        assert status == 200
        assert body["operation"]["status"] == "completed"
        assert body["operation"]["response_text"] == "verified browser response"
        assert body["operation"]["response_text_available"] is True
    finally:
        stop_server(server, thread)


def test_http_finished_duplicate_terminal_completion_can_persist_late_verified_response(
    tmp_path: Path,
) -> None:
    bridge = make_bridge(tmp_path)
    server, thread = start_server(bridge)

    try:
        operation = bridge.queue_operation("prompt", "late response after terminal acknowledgement")
        bridge.claim_next_operation()
        bridge.heartbeat(operation.operation_id)

        first_status, first_body = post_json(
            server,
            "/chat/finished",
            {
                "operation_id": operation.operation_id,
                "chat_url": "https://chatgpt.com/c/late-terminal",
            },
        )
        assert first_status == 409
        assert first_body["error"] == "Prompt completion requires verified nonblank response_text."

        completed = bridge.complete_operation(operation.operation_id, chat_url="https://chatgpt.com/c/late-terminal")
        assert completed is not None
        assert completed["status"] == "completed"
        assert completed["response_text_available"] is False

        retry_status, retry_body = post_json(
            server,
            "/chat/finished",
            {
                "operation_id": operation.operation_id,
                "chat_url": "https://chatgpt.com/c/late-terminal",
                "response_text": "response arrived after terminal acknowledgement",
                "response_text_available": True,
            },
        )

        assert retry_status == 200
        assert retry_body["operation"]["status"] == "completed"
        assert retry_body["operation"]["response_text"] == "response arrived after terminal acknowledgement"
        assert retry_body["operation"]["response_text_available"] is True
        assert retry_body["operation"]["response_source"] == "completion_ack"
    finally:
        stop_server(server, thread)


def test_http_finished_persists_and_exposes_timing(
    tmp_path: Path,
) -> None:
    bridge = make_bridge(tmp_path)
    server, thread = start_server(bridge)

    try:
        operation = bridge.queue_operation("prompt", "timed completion")
        bridge.claim_next_operation()
        bridge.heartbeat(operation.operation_id)

        timing = {
            "injected_at_ms": 1_000,
            "ack_at_ms": 1_050,
            "generation_start_ms": 2_000,
            "completed_at_ms": 62_000,
            "user_messages_added": 1,
            "ack_verified": True,
            "submission_via": "verified",
        }
        status, body = post_json(
            server,
            "/chat/finished",
            {
                "operation_id": operation.operation_id,
                "chat_url": "https://chatgpt.com/c/timing",
                "response_text": "timed response",
                "response_text_available": True,
                "timing": timing,
            },
        )

        assert status == 200
        assert body["operation"]["timing"] == timing
        persisted = bridge.get_operation(operation.operation_id)
        assert persisted is not None
        assert persisted["timing"] == timing
        assert persisted["status"] == "completed"
    finally:
        stop_server(server, thread)


def test_http_finished_rejects_non_monotonic_timing(
    tmp_path: Path,
) -> None:
    bridge = make_bridge(tmp_path)
    server, thread = start_server(bridge)

    try:
        operation = bridge.queue_operation("prompt", "bad timing")
        bridge.claim_next_operation()
        bridge.heartbeat(operation.operation_id)

        status, body = post_json(
            server,
            "/chat/finished",
            {
                "operation_id": operation.operation_id,
                "response_text": "response",
                "response_text_available": True,
                "timing": {
                    "injected_at_ms": 2_000,
                    "ack_at_ms": 1_000,
                    "ack_verified": True,
                },
            },
        )
        assert status == 400
        assert body["error"] == "invalid timing payload."
    finally:
        stop_server(server, thread)


def test_recovery_observations_are_append_only_on_operation(
    tmp_path: Path,
) -> None:
    bridge = make_bridge(tmp_path)
    operation = bridge.queue_operation("prompt", "recovery telemetry")
    bridge.claim_next_operation()
    bridge.heartbeat(operation.operation_id)

    for i in range(2):
        bridge.save_browser_observation(
            {
                "schema_version": "pasi-chatgpt-recovery-v3",
                "captured_at": f"2026-09-20T12:00:0{i}Z",
                "data": {
                    "kind": "chatgpt_recovery",
                    "operation_id": operation.operation_id,
                    "phase": "reloading" if i == 0 else "ready_for_retry",
                    "recovery_reason": "no_progress",
                    "recovery_duration_ms": 90_000 if i else None,
                    "outcome": "resumed" if i else None,
                },
            }
        )

    persisted = bridge.get_operation(operation.operation_id)
    assert persisted is not None
    events = persisted.get("recovery_events")
    assert isinstance(events, list)
    assert len(events) == 2
    assert events[0]["phase"] == "reloading"
    assert events[1]["recovery_duration_ms"] == 90_000
