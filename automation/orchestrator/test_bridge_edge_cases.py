from __future__ import annotations

import json
import threading
from http.client import HTTPConnection
from pathlib import Path

from automation.orchestrator.bridge import BridgeHTTPServer, BridgeRequestHandler, BridgeState
from automation.orchestrator.state import StateManager


def make_bridge(tmp_path: Path) -> BridgeState:
    return BridgeState(StateManager(tmp_path / ".ai"))


def post_json(
    server: BridgeHTTPServer,
    path: str,
    payload: dict[str, object],
) -> tuple[int, dict[str, object]]:
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


def test_http_finished_forces_whitespace_response_unavailable(
    tmp_path: Path,
) -> None:
    bridge = make_bridge(tmp_path)
    server, thread = start_server(bridge)

    try:
        operation = bridge.queue_operation("prompt", "whitespace")
        bridge.claim_next_operation()
        bridge.heartbeat(operation.operation_id)

        status, body = post_json(
            server,
            "/chat/finished",
            {
                "operation_id": operation.operation_id,
                "chat_url": "https://chatgpt.com/c/whitespace",
                "response_text": "   ",
                "response_text_available": True,
            },
        )

        assert status == 200
        assert body["operation"]["status"] == "completed"
        assert body["operation"]["response_text"] == "   "
        assert body["operation"]["response_text_available"] is False
        persisted = bridge.get_operation(operation.operation_id)
        assert persisted == body["operation"]
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
                "response_text": "duplicate completion",
                "response_text_available": True,
            },
        )

        assert retry_status == 409
        assert "Unsupported operation transition" in retry_body["error"]
        persisted = bridge.get_operation(operation.operation_id)
        assert persisted is not None
        assert persisted["status"] == "completed"
        assert persisted["response_text"] == "first completion"
    finally:
        stop_server(server, thread)
