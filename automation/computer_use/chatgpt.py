from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

from .adapters import AIAdapter
from .contracts import AIResponse
from .completion import completion_from_operation


class ChatGPTAdapterError(RuntimeError):
    """Raised when the ChatGPT bridge cannot satisfy an adapter operation."""


class BridgeTransport(Protocol):
    """Small HTTP transport seam for testing the ChatGPT adapter."""

    def request(self, method: str, path: str, payload: Mapping[str, Any] | None = None) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class UrllibBridgeTransport:
    """JSON transport for the localhost ChatGPT bridge."""

    base_url: str = "http://127.0.0.1:8765"
    timeout_seconds: float = 10.0
    max_response_bytes: int = 2_000_000

    def __post_init__(self) -> None:
        parsed = urlsplit(self.base_url)
        try:
            port = parsed.port
        except ValueError as exc:
            raise ValueError("ChatGPT bridge transport must target localhost HTTP") from exc
        if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.username is not None or parsed.password is not None or port is None:
            raise ValueError("ChatGPT bridge transport must target localhost HTTP")
        if self.timeout_seconds <= 0 or self.max_response_bytes <= 0:
            raise ValueError("transport bounds must be positive")

    def request(self, method: str, path: str, payload: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
        body = None
        headers: dict[str, str] = {}
        if payload is not None:
            body = json.dumps(dict(payload)).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(f"{self.base_url.rstrip('/')}/{path.lstrip('/')}", data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read(self.max_response_bytes + 1)
        except HTTPError as exc:
            detail = exc.read(self.max_response_bytes).decode("utf-8", errors="replace")
            raise ChatGPTAdapterError(f"bridge HTTP {exc.code}: {detail[:500]}") from exc
        except URLError as exc:
            raise ChatGPTAdapterError(f"bridge request failed: {exc.reason}") from exc
        if len(raw) > self.max_response_bytes:
            raise ChatGPTAdapterError("bridge response exceeded configured bound")
        try:
            result = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ChatGPTAdapterError("bridge returned invalid JSON") from exc
        if not isinstance(result, Mapping):
            raise ChatGPTAdapterError("bridge JSON response must be an object")
        return result


@dataclass
class ChatGPTAdapter(AIAdapter):
    """Semantic ChatGPT adapter built on the existing local bridge."""

    transport: BridgeTransport
    session_id: str
    poll_interval_seconds: float = 0.25
    max_wait_seconds: float = 3600.0
    current_operation_id: str | None = None

    provider: str = "chatgpt"

    def __post_init__(self) -> None:
        if not self.session_id.strip():
            raise ValueError("session_id is required")
        if self.poll_interval_seconds <= 0 or self.max_wait_seconds <= 0:
            raise ValueError("polling bounds must be positive")

    def new_session(self) -> str:
        operation = self._queue("new_chat", "")
        self.current_operation_id = self._operation_id(operation)
        result = self.wait_for_completion(self.current_operation_id)
        if result.completion != "complete":
            raise ChatGPTAdapterError(f"new ChatGPT session did not complete: {result.completion}")
        return self.current_operation_id

    def attach_github_repository(self, repository: str) -> str:
        repository = repository.strip()
        if not repository or "/" not in repository:
            raise ValueError("repository must be in owner/name form")
        operation_id = self._operation_id(self._queue("attach_github", repository))
        self.current_operation_id = operation_id
        result = self.wait_for_completion(operation_id)
        if result.completion != "complete":
            raise ChatGPTAdapterError(f"GitHub context attachment did not complete: {result.completion}")
        return operation_id

    def select_reasoning_mode(self, mode: str) -> None:
        mode = mode.strip()
        if not mode:
            raise ValueError("reasoning mode is required")
        operation_id = self._operation_id(self._queue("select_reasoning", mode))
        self.current_operation_id = operation_id
        result = self.wait_for_completion(operation_id)
        if result.completion != "complete":
            raise ChatGPTAdapterError(f"ChatGPT reasoning-mode selection did not complete: {result.completion}")

    def submit_prompt(self, prompt: str) -> str:
        if not prompt.strip():
            raise ValueError("prompt is required")
        operation_id = self._operation_id(self._queue("prompt", prompt))
        self.current_operation_id = operation_id
        return operation_id

    def read_response(self) -> AIResponse:
        if self.current_operation_id is None:
            raise ChatGPTAdapterError("no active ChatGPT operation")
        return self.read_operation(self.current_operation_id)

    def read_operation(self, operation_id: str) -> AIResponse:
        if not operation_id.strip():
            raise ValueError("operation_id is required")
        payload = self.transport.request("GET", f"/operation?operation_id={quote(operation_id, safe='')}")
        operation = payload.get("operation")
        if not isinstance(operation, Mapping):
            raise ChatGPTAdapterError("bridge response did not contain an operation")
        return self._response_from_operation(operation)

    def read_browser_observation(self) -> Mapping[str, Any] | None:
        payload = self.transport.request("GET", "/browser/observation")
        observation = payload.get("observation")
        return observation if isinstance(observation, Mapping) else None

    def wait_for_completion(self, operation_id: str, timeout_seconds: float | None = None) -> AIResponse:
        limit = self.max_wait_seconds if timeout_seconds is None else timeout_seconds
        if limit <= 0:
            raise ValueError("timeout_seconds must be positive")
        started = time.monotonic()
        while True:
            response = self.read_operation(operation_id)
            if response.completion in {"complete", "error", "interrupted"}:
                return response
            if time.monotonic() - started >= limit:
                return AIResponse(response_id=f"{operation_id}:timeout", session_id=self.session_id, provider=self.provider, operation_id=operation_id, text="", completion="timeout")
            time.sleep(self.poll_interval_seconds)

    def _queue(self, operation_type: str, prompt: str) -> Mapping[str, Any]:
        payload = self.transport.request("POST", "/queue", {"operation_type": operation_type, "prompt": prompt})
        operation = payload.get("operation")
        if not isinstance(operation, Mapping):
            raise ChatGPTAdapterError("bridge response did not contain an operation")
        return operation

    def _operation_id(self, operation: Mapping[str, Any]) -> str:
        operation_id = operation.get("operation_id")
        if not isinstance(operation_id, str) or not operation_id.strip():
            raise ChatGPTAdapterError("bridge operation_id is missing")
        return operation_id

    def _response_from_operation(self, operation: Mapping[str, Any]) -> AIResponse:
        operation_id = self._operation_id(operation)
        completion, text, response_available = completion_from_operation(operation)
        chat_url = _optional_string(operation.get("chat_url"))
        error = _optional_string(operation.get("error"))
        chat_exhausted = bool(error and error.startswith("CHAT_EXHAUSTED:"))
        completion_ack_lost = bool(error and error.startswith("PASI_NATIVE: bridge completion failed"))
        should_check_observation = operation.get("operation_type") == "prompt" and not response_available and (completion == "complete" or completion_ack_lost)

        if should_check_observation:
            try:
                observation = self.read_browser_observation()
            except ChatGPTAdapterError:
                observation = None
            data = observation.get("data") if isinstance(observation, Mapping) else None
            if isinstance(data, Mapping):
                kind = data.get("kind")
                if kind == "chatgpt_response":
                    observed_text = data.get("response_text")
                    observed_available = data.get("response_text_available") is True
                    if isinstance(observed_text, str) and observed_text.strip():
                        text = observed_text
                        response_available = observed_available or bool(observed_text.strip())
                        # Browser evidence proves the assistant answered even if the
                        # completion acknowledgement itself was lost after the server accepted it.
                        if completion_ack_lost:
                            completion = "complete"
                    observed_url = data.get("chat_url")
                    if chat_url is None and isinstance(observed_url, str):
                        chat_url = observed_url
                    chat_exhausted = chat_exhausted or data.get("chat_exhausted") is True
                elif kind == "chatgpt_state":
                    state_url = data.get("chat_url")
                    if chat_url is None and isinstance(state_url, str):
                        chat_url = state_url
                    chat_exhausted = chat_exhausted or data.get("chat_exhausted") is True

        return AIResponse(
            response_id=f"{operation_id}:response",
            session_id=self.session_id,
            provider=self.provider,
            operation_id=operation_id,
            text=text,
            completion=completion,
            response_available=response_available,
            chat_url=chat_url,
            error=error,
            chat_exhausted=chat_exhausted,
        )


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) else None
