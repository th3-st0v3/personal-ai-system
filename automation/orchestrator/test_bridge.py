from pathlib import Path
import json
import threading
from http.client import HTTPConnection, RemoteDisconnected

import pytest

from automation.orchestrator import bridge as bridge_module
from automation.orchestrator.bridge import BridgeHTTPServer, BridgeRequestHandler, BridgeState
from automation.orchestrator.operation_lifecycle import InvalidOperationTransition
from automation.orchestrator.state import StateManager


def make_bridge(tmp_path: Path) -> BridgeState:
    return BridgeState(
        StateManager(tmp_path / ".ai")
    )




class DropFirstQueueResponseHandler(BridgeRequestHandler):
    """Drop the first /queue response after the bridge has persisted the operation."""

    dropped = False

    def _send_json(
        self,
        payload: dict,
        status: int = 200,
    ) -> None:
        if self.path == "/queue" and not self.__class__.dropped:
            self.__class__.dropped = True
            self.close_connection = True
            try:
                self.connection.shutdown(2)
            except OSError:
                pass
            try:
                self.connection.close()
            except OSError:
                pass
            return
        super()._send_json(payload, status)


def post_queue(
    server: BridgeHTTPServer,
    operation_type: str,
    prompt: str,
    idempotency_key: str,
) -> tuple[int, dict]:
    connection = HTTPConnection(
        "127.0.0.1",
        server.server_address[1],
        timeout=2,
    )
    payload = json.dumps(
        {
            "operation_type": operation_type,
            "prompt": prompt,
            "idempotency_key": idempotency_key,
        }
    ).encode("utf-8")
    connection.request(
        "POST",
        "/queue",
        body=payload,
        headers={"Content-Type": "application/json"},
    )
    response = connection.getresponse()
    body = json.loads(response.read().decode("utf-8"))
    connection.close()
    return response.status, body


def test_bridge_module_resolves_from_repository() -> None:
    assert Path(bridge_module.__file__).resolve() == (Path(__file__).parent / "bridge.py").resolve()


def test_bridge_suppresses_successful_http_access_log_noise(capsys: pytest.CaptureFixture[str]) -> None:
    handler = object.__new__(BridgeRequestHandler)

    handler.log_message('"%s" %s %s', 'GET /health HTTP/1.1', '200', '42')
    assert capsys.readouterr().out == ""

    handler.log_message('"%s" %s %s', 'GET /health HTTP/1.1', '503', '42')
    assert "[Bridge]" in capsys.readouterr().out


def test_queue_idempotency_reuses_only_nonterminal_matching_operation(tmp_path: Path) -> None:
    bridge = make_bridge(tmp_path)
    first = bridge.queue_operation("prompt", "same prompt", idempotency_key="key-1")
    duplicate = bridge.queue_operation("prompt", "same prompt", idempotency_key="key-1")
    assert duplicate.operation_id == first.operation_id
    assert bridge.get_status()["history_size"] == 1

    bridge.claim_operation(first.operation_id)
    duplicate_claimed = bridge.queue_operation("prompt", "same prompt", idempotency_key="key-1")
    assert duplicate_claimed.operation_id == first.operation_id

    bridge.heartbeat(first.operation_id)
    bridge.complete_operation(first.operation_id, response_text="finished", response_text_available=True)
    replay = bridge.queue_operation("prompt", "same prompt", idempotency_key="key-1")
    assert replay.operation_id != first.operation_id
    assert bridge.get_status()["history_size"] == 2


def test_queue_idempotency_survives_bridge_restart(tmp_path: Path) -> None:
    first_bridge = make_bridge(tmp_path)
    first = first_bridge.queue_operation(
        "prompt",
        "resume after restart",
        idempotency_key="restart-key",
    )

    restarted_bridge = make_bridge(tmp_path)
    duplicate = restarted_bridge.queue_operation(
        "prompt",
        "resume after restart",
        idempotency_key="restart-key",
    )

    assert duplicate.operation_id == first.operation_id
    assert restarted_bridge.get_status()["history_size"] == 1


def test_queue_idempotency_does_not_cross_prompt_or_operation_type(tmp_path: Path) -> None:
    bridge = make_bridge(tmp_path)
    first = bridge.queue_operation("prompt", "first", idempotency_key="shared")
    second = bridge.queue_operation("prompt", "second", idempotency_key="shared")
    third = bridge.queue_operation("new_chat", "", idempotency_key="shared")
    assert len({first.operation_id, second.operation_id, third.operation_id}) == 3


def test_http_queue_response_loss_is_recovered_without_duplicate_operation(tmp_path: Path) -> None:
    DropFirstQueueResponseHandler.dropped = False
    bridge = make_bridge(tmp_path)
    server = BridgeHTTPServer(("127.0.0.1", 0), DropFirstQueueResponseHandler)
    server.bridge_state = bridge
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    operation_type = "prompt"
    prompt = "recover after HTTP response loss"
    idempotency_key = "post-queue-crash-key"

    try:
        connection = HTTPConnection(
            "127.0.0.1",
            server.server_address[1],
            timeout=2,
        )
        payload = json.dumps(
            {
                "operation_type": operation_type,
                "prompt": prompt,
                "idempotency_key": idempotency_key,
            }
        ).encode("utf-8")
        connection.request(
            "POST",
            "/queue",
            body=payload,
            headers={"Content-Type": "application/json"},
        )
        with pytest.raises(RemoteDisconnected):
            connection.getresponse()
        connection.close()
        assert DropFirstQueueResponseHandler.dropped is True
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        assert not thread.is_alive()

    restarted_bridge = make_bridge(tmp_path)
    restarted_server = BridgeHTTPServer(("127.0.0.1", 0), BridgeRequestHandler)
    restarted_server.bridge_state = restarted_bridge
    restarted_thread = threading.Thread(target=restarted_server.serve_forever, daemon=True)
    restarted_thread.start()

    try:
        status, body = post_queue(
            restarted_server,
            operation_type,
            prompt,
            idempotency_key,
        )
        assert status == 201
        assert body["operation"]["operation_id"]
        assert restarted_bridge.get_status()["history_size"] == 1
        persisted = restarted_bridge.get_operation(body["operation"]["operation_id"])
        assert persisted is not None
        assert persisted["operation_id"] == body["operation"]["operation_id"]
        assert persisted["status"] == body["operation"]["status"] == "queued"
        assert persisted["idempotency_key"] == idempotency_key
        assert persisted["prompt"] == prompt
    finally:
        restarted_server.shutdown()
        restarted_server.server_close()
        restarted_thread.join(timeout=2)
        assert not restarted_thread.is_alive()


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


def test_completed_operation_repairs_response_after_state_observation_overwrites_latest(tmp_path: Path) -> None:
    bridge = make_bridge(tmp_path)
    operation = bridge.queue_operation("prompt", "preserve response evidence")
    claimed = bridge.claim_next_operation()
    assert claimed is not None
    bridge.heartbeat(operation.operation_id)

    completed = bridge.complete_operation(
        operation.operation_id,
        chat_url="https://chatgpt.com/c/preserve",
    )
    assert completed is not None
    assert completed["status"] == "completed"
    assert completed["response_text_available"] is False

    response_observation = {
        "schema_version": "pasi-native-chromium-v2",
        "captured_at": "2026-09-17T21:50:00Z",
        "data": {
            "kind": "chatgpt_response",
            "active_operation_id": operation.operation_id,
            "chat_url": "https://chatgpt.com/c/preserve",
            "response_text": "response persisted before a later heartbeat",
            "response_text_available": True,
        },
    }
    bridge.state_manager.save_browser_response(response_observation)
    bridge.state_manager.save_browser_results(response_observation)
    bridge.state_manager.save_browser_results(
        {
            "schema_version": "pasi-native-chromium-v2",
            "captured_at": "2026-09-17T21:50:01Z",
            "data": {
                "kind": "chatgpt_state",
                "chat_url": "https://chatgpt.com/c/preserve",
                "chat_exhausted": False,
            },
        }
    )

    latest = bridge.get_operation(operation.operation_id)
    assert latest is not None
    assert latest["status"] == "completed"
    assert latest["response_text_available"] is True
    assert latest["response_text"] == "response persisted before a later heartbeat"
    assert latest["response_source"] == "browser_observation"


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


def test_completed_operation_repairs_late_browser_response_observation(tmp_path: Path) -> None:
    bridge = make_bridge(tmp_path)
    operation = bridge.queue_operation("prompt", "late observation")
    claimed = bridge.claim_next_operation()
    assert claimed is not None
    bridge.heartbeat(operation.operation_id)

    completed = bridge.complete_operation(
        operation.operation_id,
        chat_url="https://chatgpt.com/c/late",
    )
    assert completed is not None
    assert completed["status"] == "completed"
    assert completed["response_text_available"] is False

    bridge.state_manager.save_browser_response(
        {
            "schema_version": "pasi-native-chromium-v2",
            "captured_at": "2026-09-17T21:48:00Z",
            "data": {
                "kind": "chatgpt_response",
                "active_operation_id": operation.operation_id,
                "chat_url": "https://chatgpt.com/c/late",
                "response_text": "response arrived after completion acknowledgement",
                "response_text_available": True,
            },
        }
    )

    repaired = bridge.get_operation(operation.operation_id)
    assert repaired is not None
    assert repaired["status"] == "completed"
    assert repaired["response_text"] == "response arrived after completion acknowledgement"
    assert repaired["response_text_available"] is True
    assert repaired["response_source"] == "browser_observation"
    assert repaired["chat_url"] == "https://chatgpt.com/c/late"


def test_authoritative_completion_response_is_not_overwritten_by_late_observation(tmp_path: Path) -> None:
    bridge = make_bridge(tmp_path)
    operation = bridge.queue_operation("prompt", "keep authoritative response")
    claimed = bridge.claim_next_operation()
    assert claimed is not None
    bridge.heartbeat(operation.operation_id)

    completed = bridge.complete_operation(
        operation.operation_id,
        chat_url="https://chatgpt.com/c/authoritative",
        response_text="authoritative response",
        response_text_available=True,
    )
    assert completed is not None

    bridge.save_browser_observation(
        {
            "schema_version": "pasi-native-chromium-v2",
            "captured_at": "2026-09-17T21:49:00Z",
            "data": {
                "kind": "chatgpt_response",
                "active_operation_id": operation.operation_id,
                "chat_url": "https://chatgpt.com/c/stale",
                "response_text": "stale duplicate response",
                "response_text_available": True,
            },
        }
    )

    current = bridge.get_operation(operation.operation_id)
    assert current is not None
    assert current["response_text"] == "authoritative response"
    assert current["response_text_available"] is True
    assert current["chat_url"] == "https://chatgpt.com/c/authoritative"


def test_browser_response_observation_persists_to_matching_prompt(tmp_path: Path) -> None:
    bridge = make_bridge(tmp_path)
    operation = bridge.queue_operation("prompt", "observe me")
    claimed = bridge.claim_next_operation()
    assert claimed is not None

    bridge.save_browser_observation(
        {
            "schema_version": "pasi-native-chromium-v2",
            "captured_at": "2026-09-17T21:45:00Z",
            "data": {
                "kind": "chatgpt_response",
                "active_operation_id": operation.operation_id,
                "chat_url": "https://chatgpt.com/c/observe",
                "response_text": "answer preserved before acknowledgement",
                "response_text_available": True,
            },
        }
    )

    current = bridge.get_operation(operation.operation_id)
    assert current is not None
    assert current["status"] == "claimed"
    assert current["response_text"] == "answer preserved before acknowledgement"
    assert current["response_text_available"] is True
    assert current["response_source"] == "browser_observation"
    assert current["chat_url"] == "https://chatgpt.com/c/observe"


def test_browser_response_observation_derives_availability_from_nonblank_text(tmp_path: Path) -> None:
    bridge = make_bridge(tmp_path)
    operation = bridge.queue_operation("prompt", "observe stale availability")
    claimed = bridge.claim_next_operation()
    assert claimed is not None

    bridge.save_browser_observation(
        {
            "schema_version": "pasi-native-chromium-v2",
            "captured_at": "2026-09-17T21:51:00Z",
            "data": {
                "kind": "chatgpt_response",
                "active_operation_id": operation.operation_id,
                "chat_url": "https://chatgpt.com/c/stale-flag",
                "response_text": "response evidence with stale flag",
                "response_text_available": False,
            },
        }
    )

    current = bridge.get_operation(operation.operation_id)
    assert current is not None
    assert current["response_text"] == "response evidence with stale flag"
    assert current["response_text_available"] is True
    assert current["response_source"] == "browser_observation"


def test_completed_operation_repairs_late_response_with_stale_availability_flag(tmp_path: Path) -> None:
    bridge = make_bridge(tmp_path)
    operation = bridge.queue_operation("prompt", "repair stale availability")
    claimed = bridge.claim_next_operation()
    assert claimed is not None
    bridge.heartbeat(operation.operation_id)

    completed = bridge.complete_operation(
        operation.operation_id,
        chat_url="https://chatgpt.com/c/stale-repair",
    )
    assert completed is not None
    assert completed["status"] == "completed"

    bridge.state_manager.save_browser_response(
        {
            "schema_version": "pasi-native-chromium-v2",
            "captured_at": "2026-09-18T00:00:00Z",
            "data": {
                "kind": "chatgpt_response",
                "active_operation_id": operation.operation_id,
                "chat_url": "https://chatgpt.com/c/stale-repair",
                "response_text": "persisted response with stale availability flag",
                "response_text_available": False,
            },
        }
    )

    repaired = bridge.get_operation(operation.operation_id)
    assert repaired is not None
    assert repaired["response_text"] == "persisted response with stale availability flag"
    assert repaired["response_text_available"] is True
    assert repaired["response_source"] == "browser_observation"


def test_mismatched_browser_response_does_not_attach_to_operation(tmp_path: Path) -> None:
    bridge = make_bridge(tmp_path)
    operation = bridge.queue_operation("prompt", "do not attach")
    claimed = bridge.claim_next_operation()
    assert claimed is not None

    bridge.save_browser_observation(
        {
            "schema_version": "pasi-native-chromium-v2",
            "captured_at": "2026-09-17T21:46:00Z",
            "data": {
                "kind": "chatgpt_response",
                "active_operation_id": "op-from-another-task",
                "chat_url": "https://chatgpt.com/c/other",
                "response_text": "unrelated response",
                "response_text_available": True,
            },
        }
    )

    current = bridge.get_operation(operation.operation_id)
    assert current is not None
    assert not current["response_text"].strip()
    assert current["response_text_available"] is False


def test_transient_completion_ack_failure_completes_from_persisted_response(tmp_path: Path) -> None:
    bridge = make_bridge(tmp_path)
    operation = bridge.queue_operation("prompt", "do not replay")
    claimed = bridge.claim_next_operation()
    assert claimed is not None

    bridge.save_browser_observation(
        {
            "schema_version": "pasi-native-chromium-v2",
            "captured_at": "2026-09-17T21:47:00Z",
            "data": {
                "kind": "chatgpt_response",
                "active_operation_id": operation.operation_id,
                "chat_url": "https://chatgpt.com/c/recovery",
                "response_text": "the original answer survived the lost ack",
                "response_text_available": True,
            },
        }
    )

    recovered = bridge.fail_operation(
        operation.operation_id,
        "PASI_NATIVE: bridge completion failed: HTTP 502",
    )

    assert recovered is not None
    assert recovered["status"] == "completed"
    assert recovered["retry_count"] == 0
    assert recovered["response_text"] == "the original answer survived the lost ack"
    assert recovered["response_text_available"] is True
    assert recovered["completion_recovery_reason"] == "browser_response_observation_after_transient_failure"
    assert recovered["recovery_error"] == "PASI_NATIVE: bridge completion failed: HTTP 502"

    assert bridge.claim_next_operation() is None


def test_transient_browser_failure_is_requeued(tmp_path: Path) -> None:
    bridge = make_bridge(tmp_path)
    operation = bridge.queue_operation("prompt", "retry me")
    claimed = bridge.claim_next_operation()
    assert claimed is not None

    recovered = bridge.fail_operation(
        operation.operation_id,
        "Could not find ChatGPT composer.",
    )

    assert recovered is not None
    assert recovered["status"] == "queued"
    assert recovered["retry_count"] == 1
    assert recovered["last_retry_error"] == "Could not find ChatGPT composer."

    reclaimed = bridge.claim_next_operation()
    assert reclaimed is not None
    assert reclaimed["operation_id"] == operation.operation_id
    assert reclaimed["retry_count"] == 1


def test_transient_browser_failure_is_bounded(tmp_path: Path) -> None:
    bridge = make_bridge(tmp_path)
    operation = bridge.queue_operation("prompt", "bounded retries")

    for expected_retry_count in (1, 2, 3):
        claimed = bridge.claim_next_operation()
        assert claimed is not None
        recovered = bridge.fail_operation(
            operation.operation_id,
            "Could not find ChatGPT composer.",
        )
        assert recovered is not None
        assert recovered["status"] == "queued"
        assert recovered["retry_count"] == expected_retry_count

    claimed = bridge.claim_next_operation()
    assert claimed is not None
    failed = bridge.fail_operation(
        operation.operation_id,
        "Could not find ChatGPT composer.",
    )
    assert failed is not None
    assert failed["status"] == "failed"
    assert failed["failure_reason"] == "transient_retry_exhausted"


def test_non_transient_failure_remains_terminal(tmp_path: Path) -> None:
    bridge = make_bridge(tmp_path)
    operation = bridge.queue_operation("prompt", "provider failure")
    bridge.claim_next_operation()

    failed = bridge.fail_operation(
        operation.operation_id,
        "provider router failed: HTTP 429",
    )

    assert failed is not None
    assert failed["status"] == "failed"
    assert failed["retry_count"] == 0
    assert "failure_reason" not in failed


def test_http_finished_persists_completion_response(tmp_path: Path) -> None:
    bridge = make_bridge(tmp_path)
    server = BridgeHTTPServer(("127.0.0.1", 0), BridgeRequestHandler)
    server.bridge_state = bridge
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        operation = bridge.queue_operation("prompt", "integration")
        bridge.claim_next_operation()
        bridge.heartbeat(operation.operation_id)

        connection = HTTPConnection("127.0.0.1", server.server_address[1], timeout=2)
        payload = json.dumps(
            {
                "operation_id": operation.operation_id,
                "chat_url": "https://chatgpt.com/c/integration",
                "response_text": "PASI HTTP completion response",
                "response_text_available": True,
            }
        ).encode("utf-8")
        connection.request(
            "POST",
            "/chat/finished",
            body=payload,
            headers={"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        body = json.loads(response.read().decode("utf-8"))
        connection.close()

        assert response.status == 200
        assert body["operation"]["status"] == "completed"
        assert body["operation"]["response_text"] == "PASI HTTP completion response"
        assert body["operation"]["response_text_available"] is True
        assert bridge.get_operation(operation.operation_id) == body["operation"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        assert not thread.is_alive()


def test_http_browser_response_returns_durable_response_after_later_state(tmp_path: Path) -> None:
    bridge = make_bridge(tmp_path)
    bridge.save_browser_observation({
        "schema_version": "pasi-native-chromium-v2",
        "captured_at": "2026-09-18T00:00:00Z",
        "data": {
            "kind": "chatgpt_response",
            "active_operation_id": "op-durable-response",
            "chat_url": "https://chatgpt.com/c/durable",
            "response_text": "durable response evidence",
            "response_text_available": True,
        },
    })
    bridge.save_browser_observation({
        "schema_version": "pasi-native-chromium-v2",
        "captured_at": "2026-09-18T00:00:01Z",
        "data": {
            "kind": "chatgpt_state",
            "active_operation_id": "op-durable-response",
            "chat_url": "https://chatgpt.com/c/durable",
        },
    })

    server = BridgeHTTPServer(("127.0.0.1", 0), BridgeRequestHandler)
    server.bridge_state = bridge
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = HTTPConnection("127.0.0.1", server.server_address[1], timeout=2)
        connection.request("GET", "/browser/response")
        response = connection.getresponse()
        body = json.loads(response.read().decode("utf-8"))
        connection.close()

        assert response.status == 200
        assert body["observation"]["data"]["kind"] == "chatgpt_response"
        assert body["observation"]["data"]["active_operation_id"] == "op-durable-response"
        assert body["observation"]["data"]["response_text"] == "durable response evidence"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        assert not thread.is_alive()


def test_http_prompt_completion_derives_availability_from_nonblank_text(tmp_path: Path) -> None:
    bridge = make_bridge(tmp_path)
    server = BridgeHTTPServer(("127.0.0.1", 0), BridgeRequestHandler)
    server.bridge_state = bridge
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        operation = bridge.queue_operation("prompt", "derive response availability")
        claimed = bridge.claim_next_operation()
        assert claimed is not None
        bridge.heartbeat(operation.operation_id)

        connection = HTTPConnection("127.0.0.1", server.server_address[1], timeout=2)
        payload = json.dumps(
            {
                "operation_id": operation.operation_id,
                "chat_url": "https://chatgpt.com/c/derived",
                "response_text": "response evidence is present",
                "response_text_available": False,
            }
        ).encode("utf-8")
        connection.request(
            "POST",
            "/chat/finished",
            body=payload,
            headers={"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        body = json.loads(response.read().decode("utf-8"))
        connection.close()

        assert response.status == 200
        assert body["operation"]["status"] == "completed"
        assert body["operation"]["response_text"] == "response evidence is present"
        assert body["operation"]["response_text_available"] is True
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        assert not thread.is_alive()


def test_http_prompt_completion_requires_verified_nonblank_response(tmp_path: Path) -> None:
    bridge = make_bridge(tmp_path)
    server = BridgeHTTPServer(("127.0.0.1", 0), BridgeRequestHandler)
    server.bridge_state = bridge
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        operation = bridge.queue_operation("prompt", "reject blank completion")
        claimed = bridge.claim_next_operation()
        assert claimed is not None
        bridge.heartbeat(operation.operation_id)

        connection = HTTPConnection("127.0.0.1", server.server_address[1], timeout=2)
        payload = json.dumps(
            {
                "operation_id": operation.operation_id,
                "chat_url": "https://chatgpt.com/c/blank",
                "response_text": "   ",
                "response_text_available": True,
            }
        ).encode("utf-8")
        connection.request(
            "POST",
            "/chat/finished",
            body=payload,
            headers={"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        body = json.loads(response.read().decode("utf-8"))
        connection.close()

        assert response.status == 409
        assert "verified nonblank response_text" in body["error"]
        current = bridge.get_operation(operation.operation_id)
        assert current is not None
        assert current["status"] == "generating"
        assert current["response_text_available"] is False
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        assert not thread.is_alive()


def test_http_duplicate_completion_ack_is_idempotent(tmp_path: Path) -> None:
    bridge = make_bridge(tmp_path)
    server = BridgeHTTPServer(("127.0.0.1", 0), BridgeRequestHandler)
    server.bridge_state = bridge
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        operation = bridge.queue_operation("prompt", "duplicate ack")
        claimed = bridge.claim_next_operation()
        assert claimed is not None
        bridge.heartbeat(operation.operation_id)

        def post_completion(response_text: str) -> tuple[int, dict]:
            connection = HTTPConnection(
                "127.0.0.1",
                server.server_address[1],
                timeout=2,
            )
            payload = json.dumps(
                {
                    "operation_id": operation.operation_id,
                    "chat_url": "https://chatgpt.com/c/idempotent",
                    "response_text": response_text,
                    "response_text_available": True,
                }
            ).encode("utf-8")
            connection.request(
                "POST",
                "/chat/finished",
                body=payload,
                headers={"Content-Type": "application/json"},
            )
            response = connection.getresponse()
            body = json.loads(response.read().decode("utf-8"))
            connection.close()
            return response.status, body

        first_status, first_body = post_completion("authoritative response")
        second_status, second_body = post_completion("stale duplicate response")

        assert first_status == 200
        assert second_status == 200
        assert second_body["operation"] == first_body["operation"]
        assert second_body["operation"]["response_text"] == "authoritative response"
        assert bridge.get_operation(operation.operation_id) == first_body["operation"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        assert not thread.is_alive()


def test_http_transient_failure_requeues_operation(tmp_path: Path) -> None:
    bridge = make_bridge(tmp_path)
    server = BridgeHTTPServer(("127.0.0.1", 0), BridgeRequestHandler)
    server.bridge_state = bridge
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        operation = bridge.queue_operation("prompt", "recover")
        claimed = bridge.claim_next_operation()
        assert claimed is not None

        connection = HTTPConnection("127.0.0.1", server.server_address[1], timeout=2)
        payload = json.dumps(
            {
                "operation_id": operation.operation_id,
                "error": "Could not find ChatGPT composer.",
            }
        ).encode("utf-8")
        connection.request(
            "POST",
            "/chat/failed",
            body=payload,
            headers={"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        body = json.loads(response.read().decode("utf-8"))
        connection.close()

        assert response.status == 200
        assert body["operation"]["status"] == "queued"
        assert body["operation"]["retry_count"] == 1

        reclaimed = bridge.claim_next_operation()
        assert reclaimed is not None
        assert reclaimed["operation_id"] == operation.operation_id
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        assert not thread.is_alive()


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


def test_context_exhaustion_is_requeued_for_one_bounded_fresh_chat(tmp_path: Path) -> None:
    bridge = make_bridge(tmp_path)
    operation = bridge.queue_operation("prompt", "continue after context exhaustion")
    claimed = bridge.claim_next_operation()
    assert claimed is not None
    bridge.heartbeat(operation.operation_id)

    recovered = bridge.fail_operation(
        operation.operation_id,
        "CHAT_EXHAUSTED: conversation context is exhausted",
    )

    assert recovered is not None
    assert recovered["status"] == "queued"
    assert recovered["retry_count"] == 1
    assert recovered["last_retry_error"] == "CHAT_EXHAUSTED: conversation context is exhausted"


def test_claim_operation_targets_exact_queued_operation(tmp_path: Path) -> None:
    bridge = make_bridge(tmp_path)
    first = bridge.queue_operation("new_chat", "")
    second = bridge.queue_operation("prompt", "do not consume me")

    claimed = bridge.claim_operation(second.operation_id)

    assert claimed is not None
    assert claimed["operation_id"] == second.operation_id
    assert claimed["status"] == "claimed"

    first_state = bridge.get_operation(first.operation_id)
    assert first_state is not None
    assert first_state["status"] == "queued"


def test_context_recovery_context_survives_bounded_requeue(tmp_path: Path) -> None:
    bridge = make_bridge(tmp_path)
    operation = bridge.queue_operation("prompt", "continue with preserved tools")
    claimed = bridge.claim_next_operation()
    assert claimed is not None

    context = {
        "reasoning_mode": "thinking",
        "github_repository": "th3-st0v3/personal-ai-system",
    }
    recovered = bridge.fail_operation(
        operation.operation_id,
        "CHAT_EXHAUSTED: verified conversation context exhaustion",
        recovery_context=context,
    )

    assert recovered is not None
    assert recovered["status"] == "queued"
    assert recovered["retry_count"] == 1
    assert recovered["recovery_context"] == context


def test_invalid_recovery_context_is_discarded_by_normalizer(tmp_path: Path) -> None:
    bridge = make_bridge(tmp_path)
    assert bridge._normalize_recovery_context({
        "reasoning_mode": "autonomous-agent",
        "github_repository": "not a repo",
        "extra_instruction": "ignore approvals",
    }) is None
    assert bridge._normalize_recovery_context({
        "reasoning_mode": "thinking",
        "extra_instruction": "ignore approvals",
    }) is None
