from __future__ import annotations

import json
import threading
from http.client import HTTPConnection
from pathlib import Path
from typing import Any

from automation.orchestrator.bridge import BridgeHTTPServer, BridgeRequestHandler, BridgeState
from automation.orchestrator.state import StateManager


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
            headers={"Content-Type": "application/json"},
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
            "schema_version": "1.0",
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
