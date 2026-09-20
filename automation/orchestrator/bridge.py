from __future__ import annotations

import hmac
import json
import os
import threading
import time
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .config import CONFIG, ensure_runtime_directories
from .models import ChatOperation
from .operation_lifecycle import InvalidOperationTransition, validate_transition
from .state import StateManager


HOST = "127.0.0.1"
PORT = 8765
MAX_RESPONSE_TEXT_CHARS = 120_000
MAX_TRANSIENT_FAILURE_RETRIES = 3
RETRY_BUDGETS = {"controller": 3, "response": 2, "context": 1}
MAX_ERROR_CHARS = 2_000
MAX_RECOVERY_CONTEXT_REPOSITORY_CHARS = 200
MAX_IDEMPOTENCY_KEY_CHARS = 128
MAX_RECOVERY_EVENTS_PER_OPERATION = 64
MAX_TIMING_KEYS = frozenset({
    "injected_at_ms",
    "ack_at_ms",
    "generation_start_ms",
    "completed_at_ms",
    "user_messages_added",
    "ack_verified",
    "submission_via",
})
BRIDGE_TOKEN_FILE = Path.home() / ".pasi" / "bridge-token"
_TRANSIENT_BROWSER_ERROR_PREFIXES = (
    "Could not find ChatGPT composer.",
    "Composer disappeared before submission.",
    "Could not find ChatGPT send button.",
    "ChatGPT prompt submission did not leave the composer after repeated send attempts.",
    "Could not find ChatGPT plus control",
    "ChatGPT Thinking control was not found.",
    "GitHub app was not found in the ChatGPT menu.",
    "PASI browser page reloaded during operation",
    "PASI_NATIVE: browser page reloaded during operation",
    "PASI: browser page reloaded during operation",
    "PASI_NATIVE: bridge completion failed",
    "CHAT_EXHAUSTED:",
    "PASI_NATIVE: new chat did not reach a verified ready state",
    "PASI_NATIVE: new chat control did not change conversation identity",
    "PASI_NATIVE: prompt submission could not be verified after bounded attempts",
    "PASI_NATIVE: previous response still generating",
    "PASI_NATIVE: composer holds unrelated text",
    "PASI_NATIVE: submission accepted but generation did not start",
    "PASI_NATIVE: send control unavailable",
    "PASI_NATIVE: composer unavailable",
    "PASI_NATIVE: composer disappeared",
    "PASI_NATIVE: ChatGPT generation timed out",
    "PASI_NATIVE: response text unavailable",
)


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
        idempotency_key: str | None = None,
    ) -> ChatOperation:
        if idempotency_key is not None:
            if not isinstance(idempotency_key, str) or not idempotency_key.strip() or len(idempotency_key) > MAX_IDEMPOTENCY_KEY_CHARS:
                raise ValueError("idempotency_key must be a nonblank bounded string")

        with self.lock:
            queue = self.state_manager.load_queue()
            if idempotency_key is not None:
                for item in queue:
                    if (
                        item.get("idempotency_key") == idempotency_key
                        and item.get("operation_type") == operation_type
                        and item.get("prompt") == prompt
                        and item.get("status") not in {"completed", "failed", "cancelled"}
                    ):
                        fields = ChatOperation.__dataclass_fields__
                        return ChatOperation(**{key: item[key] for key in fields if key in item})

            operation = ChatOperation(
                operation_id=self._new_operation_id(),
                operation_type=operation_type,
                prompt=prompt,
                idempotency_key=idempotency_key,
                status="queued",
            )
            item = operation.to_dict()
            item["retry_count"] = 0
            queue.append(item)
            self.state_manager.save_queue(queue)
            return operation

    def claim_operation(
        self,
        operation_id: str,
    ) -> dict[str, Any] | None:
        with self.lock:
            queue = self.state_manager.load_queue()

            for item in queue:
                if item.get("operation_id") != operation_id:
                    continue
                if item.get("status") != "queued":
                    return None

                validate_transition("queued", "claimed")
                item["status"] = "claimed"
                item["claimed_at"] = time.time()
                self.state_manager.save_queue(queue)
                return dict(item)

        return None

    def claim_next_operation(self) -> dict[str, Any] | None:
        with self.lock:
            queue = self.state_manager.load_queue()

            for item in queue:
                if item.get("status") != "queued":
                    continue

                validate_transition("queued", "claimed")
                item["status"] = "claimed"
                item["claimed_at"] = time.time()

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
                if item.get("operation_id") != operation_id:
                    continue

                if self._repair_response_from_browser_observation(item):
                    self.state_manager.save_queue(queue)

                return dict(item)

        return None

    @staticmethod
    def normalize_timing(value: object) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None
        if any(key not in MAX_TIMING_KEYS for key in value):
            return None
        result: dict[str, Any] = {}
        for key in ("injected_at_ms", "ack_at_ms", "generation_start_ms", "completed_at_ms"):
            if key not in value:
                continue
            raw = value[key]
            if isinstance(raw, bool) or not isinstance(raw, (int, float)) or raw < 0:
                return None
            result[key] = float(raw) if isinstance(raw, float) else int(raw)
        if "user_messages_added" in value:
            raw = value["user_messages_added"]
            if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0 or raw > 100:
                return None
            result["user_messages_added"] = raw
        if "ack_verified" in value:
            if not isinstance(value["ack_verified"], bool):
                return None
            result["ack_verified"] = value["ack_verified"]
        if "submission_via" in value:
            raw = value["submission_via"]
            if not isinstance(raw, str) or not raw.strip() or len(raw) > 64:
                return None
            result["submission_via"] = raw.strip()
        previous: float | None = None
        for key in ("injected_at_ms", "ack_at_ms", "generation_start_ms", "completed_at_ms"):
            raw = result.get(key)
            if raw is None:
                continue
            numeric = float(raw)
            if previous is not None and numeric < previous:
                return None
            previous = numeric
        if result.get("ack_verified") is True and "ack_at_ms" not in result:
            return None
        return result

    def persist_timing(self, operation_id: str, timing: object) -> dict[str, Any] | None:
        normalized = self.normalize_timing(timing)
        if normalized is None or not operation_id.strip():
            return None
        with self.lock:
            queue = self.state_manager.load_queue()
            for item in queue:
                if item.get("operation_id") != operation_id:
                    continue
                item["timing"] = normalized
                self.state_manager.save_queue(queue)
                return dict(item)
        return None

    def append_recovery_event(
        self,
        operation_id: str,
        data: dict[str, Any],
        captured_at: object,
    ) -> dict[str, Any] | None:
        if not isinstance(operation_id, str) or not operation_id.strip():
            return None
        allowed = (
            "phase", "reason", "recovery_reason", "recovery_action",
            "replacement_reason", "reload_count", "age_ms", "idle_ms",
            "recovery_started_at_ms", "recovery_finished_at_ms",
            "recovery_duration_ms", "outcome", "observed_status", "error"
        )
        event = {key: data[key] for key in allowed if key in data}
        if isinstance(captured_at, str):
            event["captured_at"] = captured_at
        with self.lock:
            queue = self.state_manager.load_queue()
            for item in queue:
                if item.get("operation_id") != operation_id:
                    continue
                events = item.get("recovery_events")
                events = list(events) if isinstance(events, list) else []
                if not events or events[-1] != event:
                    events.append(event)
                    item["recovery_events"] = events[-MAX_RECOVERY_EVENTS_PER_OPERATION:]
                    self.state_manager.save_queue(queue)
                return dict(item)
        return None

    def persist_response_evidence(
        self,
        operation_id: str,
        chat_url: str | None,
        response_text: str,
    ) -> dict[str, Any] | None:
        """Attach verified response evidence without changing terminal status."""
        bounded_response = response_text[:MAX_RESPONSE_TEXT_CHARS]
        if not bounded_response.strip():
            return None
        with self.lock:
            queue = self.state_manager.load_queue()
            for item in queue:
                if item.get("operation_id") != operation_id or item.get("operation_type") != "prompt":
                    continue
                current = item.get("response_text")
                if item.get("response_text_available") is True and isinstance(current, str) and current.strip():
                    return dict(item)
                item["response_text"] = bounded_response
                item["response_text_available"] = True
                if isinstance(chat_url, str):
                    item["chat_url"] = chat_url
                item["response_source"] = "completion_ack"
                item["response_observed_at"] = time.time()
                self.state_manager.save_queue(queue)
                return dict(item)
        return None

    def complete_operation(
        self,
        operation_id: str,
        chat_url: str | None = None,
        response_text: str | None = None,
        response_text_available: bool = False,
        timing: object = None,
    ) -> dict[str, Any] | None:
        return self._update_operation(
            operation_id=operation_id,
            status="completed",
            chat_url=chat_url,
            response_text=response_text,
            response_text_available=response_text_available,
            timing=timing,
        )

    def fail_operation(
        self,
        operation_id: str,
        error: str,
        recovery_context: dict[str, str] | None = None,
    ) -> dict[str, Any] | None:
        if self._is_transient_browser_error(error):
            return self._retry_operation(
                operation_id=operation_id,
                error=error,
                recovery_context=recovery_context,
            )

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

    @staticmethod
    def _browser_observation_time(observation: dict[str, Any]) -> float | None:
        captured_at = observation.get("captured_at")
        if not isinstance(captured_at, str):
            return None
        try:
            value = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
        except ValueError:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.timestamp()

    @staticmethod
    def _browser_observation_priority(observation: dict[str, Any]) -> int:
        schema_version = observation.get("schema_version")
        data = observation.get("data")
        kind = data.get("kind") if isinstance(data, dict) else None

        if schema_version == "pasi-native-chromium-v2" and kind in {
            "chatgpt_health",
            "chatgpt_state",
            "chatgpt_response",
        }:
            return 100
        if schema_version == "chatgpt-controller-v2":
            return 90
        if schema_version == "pasi-chatgpt-recovery-v3":
            return 50
        return 10

    def save_browser_observation(
        self,
        observation: dict[str, Any],
    ) -> dict[str, Any]:
        with self.lock:
            self._persist_verified_response_observation(observation)
            data = observation.get("data")
            if isinstance(data, dict) and data.get("kind") == "chatgpt_response":
                timing = data.get("timing")
                active_operation_id = data.get("active_operation_id")
                if isinstance(active_operation_id, str) and timing is not None:
                    self.persist_timing(active_operation_id, timing)
                self.state_manager.save_browser_response(observation)
            if isinstance(data, dict) and data.get("kind") == "chatgpt_recovery":
                operation_id = data.get("operation_id")
                if isinstance(operation_id, str):
                    self.append_recovery_event(operation_id, data, observation.get("captured_at"))

            current = self.state_manager.load_browser_results()
            incoming_priority = self._browser_observation_priority(observation)
            current_priority = self._browser_observation_priority(current)

            incoming_time = self._browser_observation_time(observation)
            current_time = self._browser_observation_time(current)
            should_replace = incoming_priority > current_priority
            if incoming_priority == current_priority:
                if current_time is None:
                    should_replace = True
                elif incoming_time is not None and incoming_time >= current_time:
                    should_replace = True

            if should_replace:
                self.state_manager.save_browser_results(observation)

        return observation

    def get_browser_response(
        self,
    ) -> dict[str, Any] | None:
        with self.lock:
            response = self.state_manager.load_browser_response()
            return response if response else None

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

    def _persist_verified_response_observation(
        self,
        observation: dict[str, Any],
    ) -> None:
        data = observation.get("data")
        if not isinstance(data, dict) or data.get("kind") != "chatgpt_response":
            return

        operation_id = data.get("active_operation_id")
        response_text = data.get("response_text")
        response_text_available = data.get("response_text_available")
        if not isinstance(operation_id, str) or not operation_id.strip():
            return
        if not isinstance(response_text, str) or len(response_text) > MAX_RESPONSE_TEXT_CHARS:
            return
        # Nonblank response text is the persisted evidence. A stale controller
        # may report the legacy availability flag incorrectly, but that flag
        # must not discard an already-bound response. Blank text remains
        # fail-closed.
        if not response_text.strip():
            return
        response_text_available = True

        queue = self.state_manager.load_queue()
        for item in queue:
            if item.get("operation_id") != operation_id:
                continue
            if item.get("operation_type") != "prompt":
                return
            current_response = item.get("response_text")
            if item.get("response_text_available") is True and isinstance(
                current_response, str
            ) and current_response.strip():
                return

            item["response_text"] = response_text
            item["response_text_available"] = True
            chat_url = data.get("chat_url")
            if isinstance(chat_url, str):
                item["chat_url"] = chat_url
            item["response_source"] = "browser_observation"
            item["response_observed_at"] = observation.get("captured_at", time.time())
            self.state_manager.save_queue(queue)
            return

    def _repair_response_from_browser_observation(
        self,
        item: dict[str, Any],
    ) -> bool:
        if item.get("operation_type") != "prompt":
            return False
        if item.get("response_text_available") is True:
            return False

        observation = self.state_manager.load_browser_response()
        if not isinstance(observation, dict):
            return False

        data = observation.get("data")
        if not isinstance(data, dict) or data.get("kind") != "chatgpt_response":
            return False
        if data.get("active_operation_id") != item.get("operation_id"):
            return False

        response_text = data.get("response_text")
        # Nonblank, operation-bound response text is the evidence. Do not let
        # a stale controller availability flag hide already-captured text.
        if (
            not isinstance(response_text, str)
            or len(response_text) > MAX_RESPONSE_TEXT_CHARS
            or not response_text.strip()
        ):
            return False

        item["response_text"] = response_text
        item["response_text_available"] = True
        chat_url = data.get("chat_url")
        if isinstance(chat_url, str):
            item["chat_url"] = chat_url
        item["response_source"] = "browser_observation"
        item["response_observed_at"] = observation.get(
            "captured_at",
            time.time(),
        )
        return True

    @staticmethod
    def _retry_class(error: str) -> str:
        if error.startswith("CHAT_EXHAUSTED:") or error.startswith("PASI_NATIVE: context recovery exhausted:"):
            return "context"
        if error.startswith("PASI_NATIVE: ChatGPT generation timed out") or error.startswith("PASI_NATIVE: response text unavailable"):
            return "response"
        return "controller"

    def _retry_operation(
        self,
        operation_id: str,
        error: str,
        recovery_context: dict[str, str] | None = None,
    ) -> dict[str, Any] | None:
        with self.lock:
            queue = self.state_manager.load_queue()
            for item in queue:
                if item.get("operation_id") != operation_id:
                    continue
                current_status = str(item.get("status", ""))
                retry_counts = item.get("retry_counts")
                if not isinstance(retry_counts, dict):
                    retry_counts = {
                        "controller": int(item.get("retry_count", 0) or 0),
                        "response": 0,
                        "context": 0,
                    }
                retry_class = self._retry_class(error)
                count = int(retry_counts.get(retry_class, 0) or 0)

                if (
                    item.get("operation_type") == "prompt"
                    and item.get("response_text_available") is True
                    and isinstance(item.get("response_text"), str)
                    and bool(str(item.get("response_text")).strip())
                ):
                    validate_transition(current_status, "completed")
                    item["status"] = "completed"
                    item["completion_recovery_reason"] = "browser_response_observation_after_transient_failure"
                    item["recovery_error"] = error[:MAX_ERROR_CHARS]
                    item["updated_at"] = time.time()
                    self.state_manager.save_queue(queue)
                    return dict(item)

                if count >= RETRY_BUDGETS[retry_class]:
                    validate_transition(current_status, "failed")
                    item["status"] = "failed"
                    item["error"] = error[:MAX_ERROR_CHARS]
                    item["failure_reason"] = (
                        "transient_retry_exhausted"
                        if retry_class == "controller"
                        else f"{retry_class}_retry_exhausted"
                    )
                    item["retry_class"] = retry_class
                    item["updated_at"] = time.time()
                    self.state_manager.save_queue(queue)
                    return dict(item)

                retry_counts = dict(retry_counts)
                retry_counts[retry_class] = count + 1
                item["retry_class"] = retry_class
                validate_transition(current_status, "queued")
                item["status"] = "queued"
                item["retry_counts"] = retry_counts
                item["retry_count"] = sum(int(value or 0) for value in retry_counts.values())
                item["last_retry_error"] = error[:MAX_ERROR_CHARS]
                if item.get("operation_type") == "prompt" and recovery_context:
                    item["recovery_context"] = dict(recovery_context)
                item.pop("claimed_at", None)
                item["requeued_at"] = time.time()
                item["updated_at"] = time.time()
                self.state_manager.save_queue(queue)
                return dict(item)
        return None

    @staticmethod
    def _is_transient_browser_error(error: str) -> bool:
        return any(
            error.startswith(prefix)
            for prefix in _TRANSIENT_BROWSER_ERROR_PREFIXES
        )

    @staticmethod
    def _normalize_recovery_context(
        value: object,
    ) -> dict[str, str] | None:
        if not isinstance(value, dict):
            return None

        normalized: dict[str, str] = {}
        if any(key not in {"reasoning_mode", "github_repository"} for key in value):
            return None

        reasoning_mode = value.get("reasoning_mode")
        if "reasoning_mode" in value:
            if not isinstance(reasoning_mode, str):
                return None
            reasoning_mode = reasoning_mode.strip().lower()
            if reasoning_mode not in {"thinking", "think"}:
                return None
            normalized["reasoning_mode"] = "thinking"

        repository = value.get("github_repository")
        if "github_repository" in value:
            if not isinstance(repository, str):
                return None
            repository = repository.strip()
            if not (
                len(repository) <= MAX_RECOVERY_CONTEXT_REPOSITORY_CHARS
                and repository.count("/") == 1
                and all(
                    part
                    and not any(char.isspace() for char in part)
                    for part in repository.split("/", 1)
                )
            ):
                return None
            normalized["github_repository"] = repository

        return normalized or None

    def _update_operation(
        self,
        operation_id: str,
        status: str,
        chat_url: str | None = None,
        error: str | None = None,
        response_text: str | None = None,
        response_text_available: bool = False,
        timing: object = None,
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
                    item["error"] = error[:MAX_ERROR_CHARS]

                if response_text is not None:
                    bounded_response = response_text[:MAX_RESPONSE_TEXT_CHARS]
                    item["response_text"] = bounded_response
                    item["response_text_available"] = bool(
                        response_text_available
                        and bool(bounded_response.strip())
                    )

                if timing is not None:
                    normalized_timing = self.normalize_timing(timing)
                    if normalized_timing is None:
                        raise ValueError("invalid timing payload")
                    item["timing"] = normalized_timing

                self.state_manager.save_queue(queue)

                return item

        return None

    @staticmethod
    def _new_operation_id() -> str:
        import secrets

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


def _bridge_access_log_should_emit(message: str) -> bool:
    """Return true only for non-success HTTP access responses."""
    try:
        status_code = int(message.rsplit(" ", 2)[-2])
    except (ValueError, IndexError):
        return True
    return not (0 < status_code < 400)


class BridgeRequestHandler(BaseHTTPRequestHandler):
    """
    Small localhost HTTP API consumed by the Tampermonkey
    ChatGPT controller.

    CORS is intentionally restricted to ChatGPT origins.
    """

    def _expected_bridge_token(self) -> str:
        configured = os.environ.get("PASI_BRIDGE_TOKEN", "").strip()
        if configured:
            return configured
        try:
            return BRIDGE_TOKEN_FILE.read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def _request_is_authorized(self, *, require_token: bool) -> bool:
        host = self.headers.get("Host", "")
        bound_port = self.server.server_address[1] if isinstance(self.server.server_address, tuple) else PORT
        if host != f"{HOST}:{bound_port}":
            return False
        origin = self.headers.get("Origin", "").strip()
        if origin and not origin.startswith("chrome-extension://"):
            return False
        if not require_token:
            return True
        expected = self._expected_bridge_token()
        supplied = self.headers.get("Authorization", "")
        prefix = "Bearer "
        token = supplied[len(prefix):].strip() if supplied.startswith(prefix) else ""
        return bool(expected) and bool(token) and hmac.compare_digest(token, expected)

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
            "Content-Type, Authorization",
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

        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_length and content_type != "application/json":
            raise ValueError("JSON request body requires Content-Type: application/json")

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

        if path != "/health" and not self._request_is_authorized(require_token=True):
            self._send_json({"error": "Unauthorized"}, HTTPStatus.UNAUTHORIZED)
            return

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

        if path == "/browser/response":
            response = self.bridge_state.get_browser_response()

            self._send_json(
                {
                    "observation": response
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
            operation = self.bridge_state.claim_next_operation()
            self._send_json({"operation": operation})
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

        if not self._request_is_authorized(require_token=True):
            self._send_json({"error": "Unauthorized"}, HTTPStatus.UNAUTHORIZED)
            return

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
            if path == "/chat/claim":
                self._claim(payload)
                return

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

    def _claim(
        self,
        payload: dict[str, Any],
    ) -> None:
        operation_id = payload.get("operation_id")
        if not isinstance(operation_id, str) or not operation_id.strip():
            self._send_json(
                {"error": "operation_id is required."},
                HTTPStatus.BAD_REQUEST,
            )
            return

        operation = self.bridge_state.claim_operation(operation_id)
        if operation is None:
            self._send_json(
                {"error": "Operation is not queued."},
                HTTPStatus.CONFLICT,
            )
            return

        self._send_json({"operation": operation})

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

        idempotency_key = payload.get("idempotency_key")
        if idempotency_key is not None and (
            not isinstance(idempotency_key, str)
            or not idempotency_key.strip()
            or len(idempotency_key) > MAX_IDEMPOTENCY_KEY_CHARS
        ):
            self._send_json({"error": "idempotency_key must be a nonblank bounded string."}, HTTPStatus.BAD_REQUEST)
            return

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
                idempotency_key=idempotency_key,
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
        timing = payload.get("timing")

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

        # Treat nonblank response text as the evidence itself. A stale or
        # partially updated controller may omit the availability flag, but
        # must not be able to turn already-supplied response text into an
        # apparently missing response. Blank text remains fail-closed.
        if isinstance(response_text, str) and response_text.strip():
            response_text_available = True

        normalized_timing = None
        if timing is not None:
            normalized_timing = self.bridge_state.normalize_timing(timing)
            if normalized_timing is None:
                self._send_json(
                    {"error": "invalid timing payload."},
                    HTTPStatus.BAD_REQUEST,
                )
                return

        existing_operation = self.bridge_state.get_operation(operation_id)
        if existing_operation is None:
            self._send_json(
                {"error": "Operation not found."},
                HTTPStatus.NOT_FOUND,
            )
            return

        incoming_response_verified = (
            response_text_available is True
            and isinstance(response_text, str)
            and bool(response_text.strip())
        )
        if existing_operation.get("status") == "completed":
            # A duplicate acknowledgement is idempotent. A later verified
            # response payload is still valid evidence when the original
            # terminal state was persisted without response text.
            if existing_operation.get("operation_type") == "prompt" and incoming_response_verified:
                existing_operation = self.bridge_state.persist_response_evidence(
                    operation_id,
                    chat_url,
                    response_text or "",
                ) or existing_operation
            if normalized_timing is not None:
                existing_operation = self.bridge_state.persist_timing(
                    operation_id,
                    normalized_timing,
                ) or existing_operation
            self._send_json({"operation": existing_operation})
            return

        if existing_operation.get("operation_type") == "prompt":
            persisted_response_verified = (
                existing_operation.get("response_text_available") is True
                and isinstance(existing_operation.get("response_text"), str)
                and bool(str(existing_operation.get("response_text")).strip())
            )
            if not incoming_response_verified and not persisted_response_verified:
                self._send_json(
                    {
                        "error": "Prompt completion requires verified nonblank response_text."
                    },
                    HTTPStatus.CONFLICT,
                )
                return

        if (
            not (
                response_text_available is True
                and isinstance(response_text, str)
                and bool(response_text.strip())
            )
            and existing_operation.get("response_text_available") is True
        ):
            # Preserve verified response evidence already persisted by the
            # browser observation path when the acknowledgement is retried
            # without its original response payload.
            response_text = existing_operation.get("response_text")
            response_text_available = True

        try:
            operation = self.bridge_state.complete_operation(
                operation_id=operation_id,
                chat_url=chat_url,
                response_text=response_text,
                response_text_available=response_text_available,
                timing=normalized_timing,
            )
        except InvalidOperationTransition:
            # Completion acknowledgements are retried by the browser controller.
            # Once an operation is durably completed, return its persisted state
            # instead of turning a duplicate acknowledgement into a recovery loop.
            operation = self.bridge_state.get_operation(operation_id)
            if operation is None or operation.get("status") != "completed":
                raise

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

        recovery_context = payload.get("recovery_context")
        if recovery_context is not None:
            recovery_context = self.bridge_state._normalize_recovery_context(
                recovery_context
            )
            if recovery_context is None:
                self._send_json(
                    {
                        "error":
                            "recovery_context is invalid."
                    },
                    HTTPStatus.BAD_REQUEST,
                )
                return

        operation = (
            self.bridge_state.fail_operation(
                operation_id=operation_id,
                error=error,
                recovery_context=recovery_context,
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
        """Keep successful request traffic out of the long-lived bridge log."""
        message = format_string % args
        if not _bridge_access_log_should_emit(message):
            return
        print("[Bridge] " + message, flush=True)


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
