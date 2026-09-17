from __future__ import annotations

import json
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from .config import CONFIG, ensure_runtime_directories
from .models import ChatOperation
from .operation_lifecycle import InvalidOperationTransition, validate_transition
from .state import StateManager


HOST = "127.0.0.1"
PORT = 8765
MAX_RESPONSE_TEXT_CHARS = 50_000


class BridgeState:
    """
    Thread-safe in-memory view of the ChatGPT operation queue.

    Persistent copies are written through StateManager so that a
    controller restart does not lose queued operations.
    """

    def __init__(self, state_manager: StateManager):
        self.state_manager = state_manager
        self.lock = threading.RLock()

    def queue_operation(
        self,
        operation_type: str,
        prompt: str,
    ) -> ChatOperation:
        operation = ChatOperation(
            operation_id=self._new_operation_id(),
            operation_type=operation_type,
            prompt=prompt,
            status="queued",
        )

        with self.lock:
            queue = self.state_manager.load_queue()
            queue.append(operation.to_dict())
            self.state_manager.save_queue(queue)

        return operation

    def claim_next_operation(self) -> dict[str, Any] | None:
        with self.lock:
            queue = self.state_manager.load_queue()

            for item in queue:
                if item.get("status") != "queued":
                    continue

                validate_transition("queued", "claimed")
                item["status"] = "claimed"

                self.state_manager.save_queue(queue)

                return item

        return None

    def get_operation(
        self,
        operation_id: str,
    ) -> dict[str, Any] | None:
        with self.lock:
            queue = self.state_manager.load_queue()

            for item in queue:
                if item.get("operation_id") == operation_id:
                    return dict(item)

        return None

    def complete_operation(
        self,
        operation_id: str,
        chat_url: str | None = None,
        response_text: str | None = None,
        response_text_available: bool = False,
    ) -> dict[str, Any] | None:
        return self._update_operation(
            operation_id=operation_id,
            status="completed",
            chat_url=chat_url,
            response_text=response_text,
            response_text_available=response_text_available,
        )

    def fail_operation(
        self,
        operation_id: str,
        error: str,
    ) -> dict[str, Any] | None:
        return self._update_operation(
            operation_id=operation_id,
            status="failed",
            error=error,
        )

    def heartbeat(
        self,
        operation_id: str,
    ) -> dict[str, Any] | None:
        return self._update_operation(
            operation_id=operation_id,
            status="generating",
        )

    def save_browser_observation(
        self,
        observation: dict[str, Any],
    ) -> dict[str, Any]:
        with self.lock:
            self.state_manager.save_browser_results(
                observation
            )

        return observation

    def get_browser_observation(
        self,
    ) -> dict[str, Any] | None:
        with self.lock:
            observation = (
                self.state_manager.load_browser_results()
            )

            if not isinstance(observation, dict):
                return None

            return observation

    def get_status(self) -> dict[str, Any]:
        with self.lock:
            queue = self.state_manager.load_queue()

            counts: dict[str, int] = {}

            for item in queue:
                status = str(
                    item.get("status", "unknown")
                )

                counts[status] = (
                    counts.get(status, 0) + 1
                )

            active_statuses = {
                "queued",
                "claimed",
                "generating",
            }

            queue_size = sum(
                1
                for item in queue
                if item.get("status") in active_statuses
            )

            return {
                "service": "personal-ai-system-chatgpt-bridge",
                "host": HOST,
                "port": PORT,
                "queue_size": queue_size,
                "history_size": len(queue),
                "counts": counts,
            }

    def _update_operation(
        self,
        operation_id: str,
        status: str,
        chat_url: str | None = None,
        error: str | None = None,
        response_text: str | None = None,
        response_text_available: bool = False,
    ) -> dict[str, Any] | None:
        with self.lock:
            queue = self.state_manager.load_queue()

            for item in queue:
                if item.get("operation_id") != operation_id:
                    continue

                current_status = str(item.get("status", ""))
                validate_transition(current_status, status)
                item["status"] = status

                if chat_url is not None:
                    item["chat_url"] = chat_url

                if error is not None:
                    item["error"] = error

                if response_text is not None:
                    bounded_response = response_text[:MAX_RESPONSE_TEXT_CHARS]
                    item["response_text"] = bounded_response
                    item["response_text_available"] = bool(
                        response_text_available
                        and bool(bounded_response.strip())
                    )

                self.state_manager.save_queue(queue)

                return item

        return None

    @staticmethod
    def _new_operation_id() -> str:
        import secrets
        import time

        return (
            f"op-{time.time_ns()}-"
            f"{secrets.token_hex(4)}"
        )


class BridgeHTTPServer(ThreadingHTTPServer):
    """
    Typed HTTP server that carries the shared BridgeState.

    This avoids dynamically adding an undeclared attribute to
    ThreadingHTTPServer, which Pylance correctly flags.
    """

    bridge_state: BridgeState


class BridgeRequestHandler(BaseHTTPRequestHandler):
    """
    Small localhost HTTP API consumed by the Tampermonkey
    ChatGPT controller.

    CORS is intentionally restricted to ChatGPT origins.
    """

    server_version = "PersonalAIChatBridge/1.0"

    @property
    def bridge_state(self) -> BridgeState:
        return self.server.bridge_state  # type: ignore[attr-defined]

    def _set_headers(
        self,
        status: int = HTTPStatus.OK,
    ) -> None:
        origin = self.headers.get(
            "Origin",
            "",
        )

        allowed_origins = {
            "https://chatgpt.com",
            "https://www.chatgpt.com",
        }

        self.send_response(status)

        if origin in allowed_origins:
            self.send_header(
                "Access-Control-Allow-Origin",
                origin,
            )

        self.send_header(
            "Vary",
            "Origin",
        )

        self.send_header(
            "Access-Control-Allow-Methods",
            "GET, POST, OPTIONS",
        )

        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type",
        )

        self.send_header(
            "Content-Type",
            "application/json; charset=utf-8",
        )

        self.end_headers()

    def _send_json(
        self,
        payload: dict[str, Any],
        status: int = HTTPStatus.OK,
    ) -> None:
        body = json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
        ).encode("utf-8")

        self._set_headers(status)

        self.wfile.write(body)

    def _read_json(self) -> dict[str, Any]:
        raw_length = self.headers.get(
            "Content-Length",
            "0",
        )

        try:
            content_length = int(raw_length)
        except ValueError as exc:
            raise ValueError(
                "Invalid Content-Length."
            ) from exc

        if content_length < 0:
            raise ValueError(
                "Invalid Content-Length."
            )

        if content_length > 2_000_000:
            raise ValueError(
                "Request body is too large."
            )

        raw_body = self.rfile.read(
            content_length
        )

        if not raw_body:
            return {}

        payload = json.loads(
            raw_body.decode("utf-8")
        )

        if not isinstance(payload, dict):
            raise ValueError(
                "JSON body must be an object."
            )

        return payload

    def do_OPTIONS(self) -> None:
        self._set_headers(
            HTTPStatus.NO_CONTENT
        )

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/health":
            self._send_json(
                {
                    "status": "ok",
                    "service": "personal-ai-system-chatgpt-bridge",
                }
            )
            return

        if path == "/status":
            self._send_json(
                self.bridge_state.get_status()
            )
            return

        if path == "/browser/observation":
            observation = (
                self.bridge_state.get_browser_observation()
            )

            self._send_json(
                {
                    "observation": observation
                }
            )
            return

        if path == "/operation":
            operation_ids = parse_qs(parsed.query).get("operation_id", [])
            operation_id = operation_ids[0] if operation_ids else ""
            if not operation_id or len(operation_id) > 200:
                self._send_json(
                    {"error": "operation_id is required."},
                    HTTPStatus.BAD_REQUEST,
                )
                return

            operation = self.bridge_state.get_operation(operation_id)
            if operation is None:
                self._send_json(
                    {"error": "Operation not found."},
                    HTTPStatus.NOT_FOUND,
                )
                return

            self._send_json({"operation": operation})
            return

        if path == "/next-operation":
            operation = (
                self.bridge_state.claim_next_operation()
            )

            if operation is None:
                self._send_json(
                    {
                        "operation": None
                    }
                )
                return

            self._send_json(
                {
                    "operation": operation
                }
            )
            return

        self._send_json(
            {
                "error": "Not found"
            },
            HTTPStatus.NOT_FOUND,
        )

    def do_POST(self) -> None:
        path = urlparse(
            self.path
        ).path

        try:
            payload = self._read_json()
        except (
            ValueError,
            json.JSONDecodeError,
        ) as exc:
            self._send_json(
                {
                    "error": str(exc)
                },
                HTTPStatus.BAD_REQUEST,
            )
            return

        try:
            if path == "/browser/observation":
                self._browser_observation(payload)
                return

            if path == "/queue":
                self._queue(payload)
                return

            if path == "/chat/heartbeat":
                self._heartbeat(payload)
                return

            if path == "/chat/finished":
                self._finished(payload)
                return

            if path == "/chat/failed":
                self._failed(payload)
                return

            self._send_json(
                {
                    "error": "Not found"
                },
                HTTPStatus.NOT_FOUND,
            )

        except InvalidOperationTransition as exc:
            self._send_json(
                {
                    "error": str(exc)
                },
                HTTPStatus.CONFLICT,
            )
        except Exception:
            self._send_json(
                {
                    "error": "Internal server error."
                },
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def _browser_observation(
        self,
        payload: dict[str, Any],
    ) -> None:
        observation = payload.get(
            "observation"
        )

        if not isinstance(
            observation,
            dict,
        ):
            self._send_json(
                {
                    "error":
                        "observation must be an object."
                },
                HTTPStatus.BAD_REQUEST,
            )
            return

        schema_version = observation.get(
            "schema_version"
        )

        if not isinstance(
            schema_version,
            str,
        ) or not schema_version.strip():
            self._send_json(
                {
                    "error":
                        "observation.schema_version is required."
                },
                HTTPStatus.BAD_REQUEST,
            )
            return

        saved = (
            self.bridge_state.save_browser_observation(
                observation
            )
        )

        self._send_json(
            {
                "observation": saved
            },
            HTTPStatus.CREATED,
        )


    def _queue(
        self,
        payload: dict[str, Any],
    ) -> None:
        operation_type = payload.get(
            "operation_type"
        )

        prompt = payload.get(
            "prompt"
        )

        if not isinstance(
            operation_type,
            str,
        ) or not operation_type.strip():
            self._send_json(
                {
                    "error":
                        "operation_type is required."
                },
                HTTPStatus.BAD_REQUEST,
            )
            return

        if not isinstance(
            prompt,
            str,
        ):
            self._send_json(
                {
                    "error":
                        "prompt must be a string."
                },
                HTTPStatus.BAD_REQUEST,
            )
            return

        if operation_type != "new_chat" and not prompt.strip():
            self._send_json(
                {
                    "error":
                        "prompt is required for this operation type."
                },
                HTTPStatus.BAD_REQUEST,
            )
            return

        operation = (
            self.bridge_state.queue_operation(
                operation_type=operation_type,
                prompt=prompt,
            )
        )

        self._send_json(
            {
                "operation": operation.to_dict()
            },
            HTTPStatus.CREATED,
        )

    def _heartbeat(
        self,
        payload: dict[str, Any],
    ) -> None:
        operation_id = payload.get(
            "operation_id"
        )

        if not isinstance(
            operation_id,
            str,
        ):
            self._send_json(
                {
                    "error":
                        "operation_id is required."
                },
                HTTPStatus.BAD_REQUEST,
            )
            return

        operation = (
            self.bridge_state.heartbeat(
                operation_id
            )
        )

        if operation is None:
            self._send_json(
                {
                    "error":
                        "Operation not found."
                },
                HTTPStatus.NOT_FOUND,
            )
            return

        self._send_json(
            {
                "operation": operation
            }
        )

    def _finished(
        self,
        payload: dict[str, Any],
    ) -> None:
        operation_id = payload.get(
            "operation_id"
        )

        chat_url = payload.get(
            "chat_url"
        )

        response_text = payload.get(
            "response_text"
        )

        response_text_available = payload.get(
            "response_text_available",
            False,
        )

        if not isinstance(
            operation_id,
            str,
        ):
            self._send_json(
                {
                    "error":
                        "operation_id is required."
                },
                HTTPStatus.BAD_REQUEST,
            )
            return

        if chat_url is not None and not isinstance(
            chat_url,
            str,
        ):
            self._send_json(
                {
                    "error":
                        "chat_url must be a string."
                },
                HTTPStatus.BAD_REQUEST,
            )
            return

        if response_text is not None and not isinstance(
            response_text,
            str,
        ):
            self._send_json(
                {
                    "error":
                        "response_text must be a string."
                },
                HTTPStatus.BAD_REQUEST,
            )
            return

        if not isinstance(
            response_text_available,
            bool,
        ):
            self._send_json(
                {
                    "error":
                        "response_text_available must be a boolean."
                },
                HTTPStatus.BAD_REQUEST,
            )
            return

        if response_text is not None and len(response_text) > MAX_RESPONSE_TEXT_CHARS:
            self._send_json(
                {
                    "error":
                        f"response_text exceeds {MAX_RESPONSE_TEXT_CHARS} characters."
                },
                HTTPStatus.BAD_REQUEST,
            )
            return

        operation = (
            self.bridge_state.complete_operation(
                operation_id=operation_id,
                chat_url=chat_url,
                response_text=response_text,
                response_text_available=response_text_available,
            )
        )

        if operation is None:
            self._send_json(
                {
                    "error":
                        "Operation not found."
                },
                HTTPStatus.NOT_FOUND,
            )
            return

        self._send_json(
            {
                "operation": operation
            }
        )

    def _failed(
        self,
        payload: dict[str, Any],
    ) -> None:
        operation_id = payload.get(
            "operation_id"
        )

        error = payload.get(
            "error"
        )

        if not isinstance(
            operation_id,
            str,
        ):
            self._send_json(
                {
                    "error":
                        "operation_id is required."
                },
                HTTPStatus.BAD_REQUEST,
            )
            return

        if not isinstance(
            error,
            str,
        ) or not error.strip():
            self._send_json(
                {
                    "error":
                        "error is required."
                },
                HTTPStatus.BAD_REQUEST,
            )
            return

        operation = (
            self.bridge_state.fail_operation(
                operation_id=operation_id,
                error=error,
            )
        )

        if operation is None:
            self._send_json(
                {
                    "error":
                        "Operation not found."
                },
                HTTPStatus.NOT_FOUND,
            )
            return

        self._send_json(
            {
                "operation": operation
            }
        )

    def log_message(
        self,
        format_string: str,
        *args: Any,
    ) -> None:
        print(
            "[Bridge] "
            + format_string % args
        )


class ChatGPTBridge:
    def __init__(
        self,
        host: str = HOST,
        port: int = PORT,
    ):
        ensure_runtime_directories()

        self.host = host
        self.port = port

        state_manager = StateManager(
            CONFIG.ai_dir
        )

        self.bridge_state = BridgeState(
            state_manager
        )

        self.server = BridgeHTTPServer(
            (self.host, self.port),
            BridgeRequestHandler,
        )

        self.server.bridge_state = self.bridge_state

    def run(self) -> None:
        print()
        print(
            "=== CHATGPT LOCAL BRIDGE ==="
        )
        print()
        print(
            f"Listening on http://{self.host}:{self.port}"
        )
        print()
        print(
            "Endpoints:"
        )
        print(
            "  GET  /health"
        )
        print(
            "  GET  /status"
        )
        print(
            "  GET  /next-operation"
        )
        print(
            "  GET  /operation?operation_id=<id>"
        )
        print(
            "  POST /queue"
        )
        print(
            "  POST /chat/heartbeat"
        )
        print(
            "  POST /chat/finished"
        )
        print(
            "  POST /chat/failed"
        )
        print()
        print(
            "Press Ctrl+C to stop."
        )
        print()

        try:
            self.server.serve_forever()
        except KeyboardInterrupt:
            print()
            print(
                "Stopping bridge..."
            )
        finally:
            self.server.server_close()


def main() -> None:
    bridge = ChatGPTBridge()
    bridge.run()


if __name__ == "__main__":
    main()
