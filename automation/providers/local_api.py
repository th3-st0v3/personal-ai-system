from __future__ import annotations

import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .ollama import OllamaProvider
from .protocol import ChatMessage


class LocalProviderAPI(BaseHTTPRequestHandler):
    """Local PASI model API. Bound to loopback by default; never exposed publicly."""

    server_version = "PASI-Provider/0.1"

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._json(HTTPStatus.OK, self.server.provider.health())  # type: ignore[attr-defined]
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path != "/v1/chat/completions":
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 1_000_000:
                raise ValueError("invalid request body size")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            messages = payload.get("messages")
            if not isinstance(messages, list) or not messages:
                raise ValueError("messages must be a non-empty list")
            parsed = [ChatMessage(role=str(item["role"]), content=str(item["content"])) for item in messages]
            result = self.server.provider.generate(parsed, model=payload.get("model"))  # type: ignore[attr-defined]
            self._json(HTTPStatus.OK, {
                "id": "pasi-local-completion",
                "object": "chat.completion",
                "model": result.model,
                "choices": [{"index": 0, "message": {"role": "assistant", "content": result.text}, "finish_reason": "stop"}],
                "provider": result.provider,
                "latency_ms": result.latency_ms,
            })
        except ValueError as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except Exception as exc:
            self._json(HTTPStatus.BAD_GATEWAY, {"error": str(exc)[:500]})

    def log_message(self, format: str, *args: object) -> None:
        return


def serve(host: str | None = None, port: int | None = None) -> None:
    bind_host = host or os.environ.get("PASI_PROVIDER_HOST", "127.0.0.1")
    bind_port = int(port if port is not None else os.environ.get("PASI_PROVIDER_PORT", "8787"))
    provider = OllamaProvider()
    server = ThreadingHTTPServer((bind_host, bind_port), LocalProviderAPI)
    server.provider = provider  # type: ignore[attr-defined]
    print(f"PASI local provider API listening on http://{bind_host}:{bind_port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    serve()
